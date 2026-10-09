from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_staff
from ..models import Batch, Medicine, Prescription, Transaction, User
from ..utils import money_json
from ..services.stock import today, total_stock_map, usable_clause, usable_stock_map

router = APIRouter(prefix="/reports", tags=["reports"])


def _day_bounds(d: date):
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)  # sales days are UTC days
    return start, start + timedelta(days=1)


def _sales_summary(db: Session, d: date) -> dict:
    start, end = _day_bounds(d)
    rows = list(db.scalars(select(Transaction).where(Transaction.created_at >= start, Transaction.created_at < end)
                           .order_by(Transaction.id)))
    zero = Decimal("0.00")
    return {"date": d.isoformat(), "transactions": len(rows),
            "subtotal": sum((t.subtotal for t in rows), zero), "discount": sum((t.discount for t in rows), zero),
            "tax": sum((t.tax for t in rows), zero), "total": sum((t.total_amount for t in rows), zero),
            "items": [{"id": t.id, "prescription_id": t.prescription_id, "pharmacist_id": t.pharmacist_id,
                       "total_amount": t.total_amount, "created_at": t.created_at} for t in rows]}


@router.get("/dashboard")
def dashboard(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    t = today()
    usable = usable_stock_map(db)
    soon = t + timedelta(days=settings.EXPIRY_WARNING_DAYS)
    expiring = db.scalar(select(func.count()).select_from(Batch)
                         .where(usable_clause(t), Batch.expiry_date <= soon)) or 0
    med_ids = list(db.scalars(select(Medicine.id)))
    sales = _sales_summary(db, datetime.now(timezone.utc).date())
    return money_json({"total_units": sum(usable.values()), "expiring_soon_batches": expiring,
                       "out_of_stock_count": sum(1 for i in med_ids if usable.get(i, 0) == 0),
                       "todays_sales": sales["total"], "todays_transactions": sales["transactions"]})


@router.get("/inventory")
def inventory_report(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    t = today()
    soon = t + timedelta(days=settings.EXPIRY_WARNING_DAYS)
    usable, total = usable_stock_map(db), total_stock_map(db)
    value: dict[int, Decimal] = {}
    expiring: dict[int, int] = {}
    for b in db.scalars(select(Batch).where(usable_clause(t))):
        value[b.medicine_id] = value.get(b.medicine_id, Decimal("0")) + b.selling_price * b.quantity
        if b.expiry_date <= soon:
            expiring[b.medicine_id] = expiring.get(b.medicine_id, 0) + b.quantity
    rows = []
    for m in db.scalars(select(Medicine).order_by(Medicine.medicine_name)):
        u, tot = usable.get(m.id, 0), total.get(m.id, 0)
        rows.append({"medicine_id": m.id, "medicine_name": m.medicine_name, "usable_units": u,
                     "expired_or_unusable_units": tot - u, "expiring_soon_units": expiring.get(m.id, 0),
                     "reorder_level": m.reorder_level, "low_stock": u <= m.reorder_level,
                     "stock_value": value.get(m.id, Decimal("0.00")).quantize(Decimal("0.01"))})
    return money_json({"generated_on": t.isoformat(), "medicines": rows,
                       "total_stock_value": sum((r["stock_value"] for r in rows), Decimal("0.00"))})


@router.get("/sales")
def sales_report(report_date: date | None = None, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    return money_json(_sales_summary(db, report_date or datetime.now(timezone.utc).date()))


@router.get("/prescriptions")
def prescription_report(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    rows = db.execute(select(Prescription.status, func.count()).group_by(Prescription.status)).all()
    by_status = {s: c for s, c in rows}
    return {"total": sum(by_status.values()), "by_status": by_status}
