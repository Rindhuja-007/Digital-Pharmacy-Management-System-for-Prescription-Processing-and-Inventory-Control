"""Dispensing: ONE database transaction, row locks, FEFO allocation, all-or-nothing."""
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from ..errors import AppError
from ..models import (ItemStatus, Prescription, PrescriptionItem, RxStatus, Transaction,
                      TransactionItem, User)
from .alerts import refresh_alerts
from .audit import log_action
from .stock import usable_batches

CENT = Decimal("0.01")


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT)


def dispense(db: Session, prescription_id: int, pharmacist: User, confirmed_dispensing: bool,
             discount: Decimal, tax: Decimal) -> Transaction:
    # Cheap request-level checks first: nothing has been touched yet.
    if confirmed_dispensing is not True:
        raise AppError(422, "confirmed_dispensing must be true to dispense")
    if discount < 0 or tax < 0:
        raise AppError(422, "discount and tax cannot be negative")
    try:
        tx = _dispense(db, prescription_id, pharmacist, _q(discount), _q(tax))
        db.commit()
        return tx
    except Exception:
        db.rollback()  # undo stock deductions, transaction rows, status change, audit entry
        raise


def _dispense(db: Session, prescription_id: int, pharmacist: User, discount: Decimal, tax: Decimal) -> Transaction:
    # Atomic claim: only a VERIFIED prescription flips to DISPENSED, and only one request can win.
    # (On PostgreSQL this also row-locks the prescription until commit.)
    claimed = db.execute(
        update(Prescription)
        .where(Prescription.id == prescription_id, Prescription.status == RxStatus.VERIFIED.value)
        .values(status=RxStatus.DISPENSED.value),
        execution_options={"synchronize_session": False}).rowcount
    if claimed != 1:
        current = db.scalar(select(Prescription.status).where(Prescription.id == prescription_id))
        if current is None:
            raise AppError(404, "Prescription not found")
        raise AppError(409, f"Prescription must be VERIFIED to dispense (current status: {current})")

    rx = db.scalar(select(Prescription).where(Prescription.id == prescription_id)
                   .options(selectinload(Prescription.items).selectinload(PrescriptionItem.medicine))
                   .execution_options(populate_existing=True))
    items = [i for i in rx.items if i.verification_status == ItemStatus.VERIFIED.value]
    if not items:
        raise AppError(409, "Prescription has no verified items")
    for i in items:
        if i.medicine_id is None or not i.quantity or i.quantity <= 0:
            raise AppError(409, f"Verified item '{i.extracted_medicine_name}' has no medicine or quantity")

    # Lock every usable batch (SELECT ... FOR UPDATE, FEFO order). Medicines are locked in id order
    # so two concurrent dispenses cannot deadlock on each other.
    locked = {mid: usable_batches(db, mid, lock=True) for mid in sorted({i.medicine_id for i in items})}

    tx = Transaction(prescription_id=rx.id, pharmacist_id=pharmacist.id, subtotal=Decimal("0.00"),
                     discount=discount, tax=tax, total_amount=Decimal("0.00"), transaction_type="SALE")
    db.add(tx)
    db.flush()

    subtotal = Decimal("0.00")
    for item in items:
        batches = locked[item.medicine_id]
        if sum(b.quantity for b in batches) < item.quantity:
            raise AppError(409, f"Insufficient usable stock for {item.medicine.medicine_name}")
        remaining = item.quantity
        for b in batches:  # already ORDER BY expiry_date, id
            if remaining == 0:
                break
            take = min(b.quantity, remaining)
            if take <= 0:
                continue
            b.quantity -= take
            remaining -= take
            line = _q(b.selling_price * take)
            db.add(TransactionItem(transaction_id=tx.id, medicine_id=item.medicine_id, batch_id=b.id,
                                   quantity=take, unit_price=b.selling_price, total_price=line))
            subtotal += line

    if discount > subtotal:
        raise AppError(422, "Discount cannot be greater than the subtotal")
    tx.subtotal = subtotal
    tx.total_amount = _q(subtotal - discount + tax)

    log_action(db, pharmacist.id, "DISPENSE", "prescription", rx.id,
               f"Dispensed {rx.prescription_number} by {pharmacist.username}; total {tx.total_amount}")
    refresh_alerts(db)
    db.flush()
    return db.scalar(select(Transaction).where(Transaction.id == tx.id)
                     .options(selectinload(Transaction.items).selectinload(TransactionItem.medicine),
                              selectinload(Transaction.items).selectinload(TransactionItem.batch))
                     .execution_options(populate_existing=True))


def receipt_dict(tx: Transaction) -> dict:
    rx = tx.prescription
    return {
        "id": tx.id, "prescription_id": tx.prescription_id,
        "prescription_number": rx.prescription_number if rx else None,
        "patient_reference": rx.patient_reference if rx else None,
        "pharmacist_id": tx.pharmacist_id, "pharmacist_username": tx.pharmacist.username,
        "subtotal": tx.subtotal, "discount": tx.discount, "tax": tx.tax, "total_amount": tx.total_amount,
        "transaction_type": tx.transaction_type, "created_at": tx.created_at,
        "items": [{"medicine_id": i.medicine_id, "medicine_name": i.medicine.medicine_name,
                   "batch_id": i.batch_id, "batch_number": i.batch.batch_number,
                   "expiry_date": i.batch.expiry_date, "quantity": i.quantity,
                   "unit_price": i.unit_price, "total_price": i.total_price} for i in tx.items],
    }
