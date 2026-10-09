"""Prescription pipeline business logic. NOTHING here changes stock; only dispensing.py does."""
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..errors import AppError, not_found
from ..models import (ItemStatus, Medicine, Prescription, PrescriptionItem, RxStatus, User)
from . import ocr as ocr_service
from .audit import log_action
from .extraction import extract_medicine_lines
from .matching import match_item
from .preprocessing import decode_image_bytes, preprocess_image
from .stock import usable_batches, usable_stock_map

EDITABLE = (RxStatus.UPLOADED.value, RxStatus.PROCESSED.value)


def _detect_ext(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    return None


def get_prescription(db: Session, rx_id: int, with_items: bool = True) -> Prescription:
    stmt = select(Prescription).where(Prescription.id == rx_id)
    if with_items:
        stmt = stmt.options(selectinload(Prescription.items))
    rx = db.scalar(stmt)
    if not rx:
        raise not_found("Prescription")
    return rx


def _require_editable(rx: Prescription, action: str):
    if rx.status not in EDITABLE:
        raise AppError(409, f"Cannot {action}: prescription is {rx.status}")


def abs_path(rel: str) -> Path:
    base = settings.UPLOAD_DIR
    p = (base / rel).resolve()
    if base not in p.parents:  # never serve/read outside the upload folder
        raise AppError(400, "Invalid file path")
    return p


# ---- 1. upload ----------------------------------------------------------------------------
def create_prescription(db: Session, user: User, data: bytes, content_type: str | None, filename: str | None,
                        patient_reference: str | None, doctor_name: str | None) -> Prescription:
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise AppError(413, "Image is larger than 10 MB")
    suffix = Path(filename or "").suffix.lower()
    ext = _detect_ext(data)
    if suffix not in (".jpg", ".jpeg", ".png") or content_type not in ("image/jpeg", "image/png") or ext is None:
        raise AppError(422, "Only JPG and PNG images are accepted")
    decode_image_bytes(data)  # proves it is a real, reasonably sized image

    folder = settings.UPLOAD_DIR / "prescriptions"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (folder / name).write_bytes(data)
    try:
        rx = Prescription(prescription_number="RX-" + uuid.uuid4().hex[:12].upper(),
                          patient_reference=(patient_reference or "").strip() or None,
                          doctor_name=(doctor_name or "").strip() or None,
                          image_path=f"prescriptions/{name}", status=RxStatus.UPLOADED.value,
                          created_by=user.id)
        db.add(rx)
        db.flush()
        log_action(db, user.id, "UPLOAD_PRESCRIPTION", "prescription", rx.id,
                   f"Uploaded prescription {rx.prescription_number}")
        db.commit()
    except Exception:
        db.rollback()
        (folder / name).unlink(missing_ok=True)
        raise
    return rx


# ---- 2. preprocess / 3. OCR -----------------------------------------------------------------
def run_preprocess(db: Session, rx_id: int) -> Prescription:
    rx = get_prescription(db, rx_id)
    _require_editable(rx, "preprocess")
    src = abs_path(rx.image_path)
    dst = src.with_name(src.stem + "_processed.png")
    preprocess_image(src, dst)
    rx.processed_image_path = str(dst.relative_to(settings.UPLOAD_DIR))
    db.commit()  # status stays UPLOADED
    return rx


def run_ocr_stage(db: Session, rx_id: int, source: str = "auto") -> Prescription:
    rx = get_prescription(db, rx_id)
    _require_editable(rx, "run OCR")
    use_processed = (source == "processed" or (source == "auto" and rx.processed_image_path))
    if use_processed and not rx.processed_image_path:
        raise AppError(409, "Run preprocessing first")
    path = abs_path(rx.processed_image_path if use_processed else rx.image_path)
    text, confidence = ocr_service.run_ocr(path)   # module attribute lookup => patchable in tests
    rx.extracted_text = text
    rx.confidence_score = confidence
    rx.status = RxStatus.PROCESSED.value           # PROCESSED only means "text was read"; no approval
    db.commit()
    return rx


# ---- 4. extract -----------------------------------------------------------------------------
def run_extract(db: Session, rx_id: int) -> tuple[Prescription, list[dict]]:
    rx = get_prescription(db, rx_id)
    _require_editable(rx, "extract")
    if rx.extracted_text is None:
        raise AppError(409, "Run OCR before extracting medicine lines")
    if any(i.verification_status != ItemStatus.PENDING.value for i in rx.items):
        raise AppError(409, "Cannot re-extract: some lines are already verified or rejected")
    result = extract_medicine_lines(rx.extracted_text)
    rx.items.clear()  # re-running replaces earlier PENDING suggestions
    db.flush()
    for line in result.items:
        rx.items.append(PrescriptionItem(
            extracted_medicine_name=line.name, dosage=line.strength, frequency=line.frequency,
            duration=line.duration, quantity=line.quantity, confidence_score=rx.confidence_score,
            verification_status=ItemStatus.PENDING.value))
    db.commit()
    return rx, result.skipped


# ---- 5. match -------------------------------------------------------------------------------
def run_match(db: Session, rx_id: int) -> list[dict]:
    rx = get_prescription(db, rx_id)
    if rx.status == RxStatus.DISPENSED.value:
        raise AppError(409, "Prescription is already dispensed")
    medicines = list(db.scalars(select(Medicine)))
    usable = usable_stock_map(db)
    results = []
    for item in rx.items:
        res = match_item(item.extracted_medicine_name, item.dosage, medicines, usable)
        results.append({"item_id": item.id, "extracted_medicine_name": item.extracted_medicine_name, **res})
        top = res["candidates"][0] if res["candidates"] else None
        if top and item.verification_status == ItemStatus.PENDING.value:
            # stored as a SUGGESTION on a PENDING line only; verification still needs an explicit decision
            item.medicine_id = top["medicine_id"]
            item.matched_medicine_name = top["medicine_name"]
            item.confidence_score = top["score"]
    db.commit()
    return results


# ---- 6. manual item -------------------------------------------------------------------------
def add_item(db: Session, rx_id: int, body) -> PrescriptionItem:
    rx = get_prescription(db, rx_id, with_items=False)
    _require_editable(rx, "add a line")
    matched = None
    if body.medicine_id is not None:
        med = db.get(Medicine, body.medicine_id)
        if not med:
            raise not_found("Medicine")
        matched = med.medicine_name
    item = PrescriptionItem(prescription_id=rx.id, medicine_id=body.medicine_id,
                            extracted_medicine_name=body.extracted_medicine_name, matched_medicine_name=matched,
                            dosage=body.dosage, frequency=body.frequency, duration=body.duration,
                            quantity=body.quantity or 1, verification_status=ItemStatus.PENDING.value)
    db.add(item)
    db.commit()
    return item


# ---- 7. verify ------------------------------------------------------------------------------
def verify(db: Session, rx_id: int, user: User, decisions) -> Prescription:
    rx = get_prescription(db, rx_id)
    if rx.status in (RxStatus.DISPENSED.value,):
        raise AppError(409, "Prescription is already dispensed and can no longer be changed")
    if not rx.items:
        raise AppError(422, "Prescription has no lines to verify; add at least one line")

    by_id = {i.id: i for i in rx.items}
    seen = [d.item_id for d in decisions]
    if len(set(seen)) != len(seen):
        raise AppError(422, "Each line may appear only once in the decisions")
    unknown = [i for i in seen if i not in by_id]
    if unknown:
        raise AppError(422, f"Unknown line id(s): {unknown}")
    missing = [i for i in by_id if i not in seen]
    if missing:
        raise AppError(422, f"A decision is required for every line; missing line id(s): {missing}")

    # validate everything first, then apply: a 422 leaves the prescription untouched
    meds: dict[int, Medicine] = {}
    for d in decisions:
        if d.decision != ItemStatus.VERIFIED.value:
            continue
        name = by_id[d.item_id].extracted_medicine_name
        if d.medicine_id is None:
            raise AppError(422, f"'{name}': choose a catalogue medicine before verifying")
        med = meds.get(d.medicine_id) or db.get(Medicine, d.medicine_id)
        if med is None:
            raise AppError(422, f"'{name}': the selected medicine does not exist")
        meds[d.medicine_id] = med
        if d.quantity is None or d.quantity <= 0:
            raise AppError(422, f"'{name}': quantity must be greater than 0")

    verified = rejected = 0
    for d in decisions:
        item = by_id[d.item_id]
        if d.decision == ItemStatus.VERIFIED.value:
            item.verification_status = ItemStatus.VERIFIED.value
            item.medicine_id = d.medicine_id
            item.matched_medicine_name = meds[d.medicine_id].medicine_name
            item.quantity = d.quantity
            verified += 1
        else:
            item.verification_status = ItemStatus.REJECTED.value
            rejected += 1
        for f in ("dosage", "frequency", "duration"):
            v = getattr(d, f)
            if v is not None:
                setattr(item, f, v.strip() or None)

    rx.status = RxStatus.VERIFIED.value if verified else RxStatus.REJECTED.value
    rx.verified_by = user.id
    rx.verified_at = datetime.now(timezone.utc)
    log_action(db, user.id, "VERIFY_PRESCRIPTION" if verified else "REJECT_PRESCRIPTION", "prescription", rx.id,
               f"{rx.prescription_number}: {verified} verified, {rejected} rejected by {user.username}")
    db.commit()
    return rx


# ---- 8. availability ------------------------------------------------------------------------
def availability(db: Session, rx_id: int) -> dict:
    rx = get_prescription(db, rx_id)
    pool: dict[int, int] = {}        # stock still unclaimed per medicine, so two lines can't both use it
    rows = []
    for item in rx.items:
        if item.verification_status != ItemStatus.VERIFIED.value or item.medicine_id is None:
            continue
        batches = usable_batches(db, item.medicine_id)
        if item.medicine_id not in pool:
            pool[item.medicine_id] = sum(b.quantity for b in batches)
        needed = item.quantity or 0
        available = pool[item.medicine_id]
        pool[item.medicine_id] = max(0, available - needed)
        name = item.matched_medicine_name or item.extracted_medicine_name
        rows.append({"item_id": item.id, "medicine_id": item.medicine_id, "medicine_name": name,
                     "needed": needed, "available": available, "shortage": max(0, needed - available),
                     "batches": [{"batch_id": b.id, "batch_number": b.batch_number, "quantity": b.quantity,
                                  "expiry_date": b.expiry_date, "selling_price": b.selling_price} for b in batches]})
    return {"prescription_id": rx.id, "status": rx.status, "items": rows,
            "can_dispense": rx.status == RxStatus.VERIFIED.value and bool(rows)
                            and all(r["shortage"] == 0 for r in rows)}


def list_prescriptions(db: Session, status: str | None, limit: int, offset: int) -> list[Prescription]:
    stmt = select(Prescription).order_by(Prescription.id.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Prescription.status == status.upper())
    rows = list(db.scalars(stmt))
    counts = dict(db.execute(select(PrescriptionItem.prescription_id, func.count())
                             .where(PrescriptionItem.prescription_id.in_([r.id for r in rows] or [0]))
                             .group_by(PrescriptionItem.prescription_id)).all())
    for r in rows:
        r.item_count = counts.get(r.id, 0)
    return rows
