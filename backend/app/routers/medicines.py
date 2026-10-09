from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin, require_staff
from ..errors import AppError, not_found
from ..models import Batch, Medicine, PrescriptionItem, TransactionItem, User
from ..schemas import MedicineIn, MedicineOut, MedicineUpdate
from ..services.alerts import refresh_alerts
from ..services.audit import log_action
from ..services.csv_import import SAMPLE_CSV, import_medicines_csv

router = APIRouter(prefix="/medicines", tags=["medicines"])


@router.get("", response_model=list[MedicineOut])
def list_medicines(q: str | None = None, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                   _: User = Depends(require_staff), db: Session = Depends(get_db)):
    stmt = select(Medicine).order_by(Medicine.medicine_name, Medicine.id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(*(c.ilike(like) for c in (
            Medicine.medicine_name, Medicine.brand_name, Medicine.generic_name,
            Medicine.composition, Medicine.barcode))))
    return list(db.scalars(stmt.limit(limit).offset(offset)))


@router.get("/sample-csv")
def sample_csv(_: User = Depends(require_staff)):
    return Response(SAMPLE_CSV, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="medicines-sample.csv"'})


@router.post("/import-csv")
async def import_csv(file: UploadFile = File(...), user: User = Depends(require_staff),
                     db: Session = Depends(get_db)):
    raw = await file.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise AppError(413, "CSV file is larger than 2 MB")
    result = import_medicines_csv(db, raw, user.id)
    refresh_alerts(db)
    db.commit()
    return result


@router.get("/{medicine_id}", response_model=MedicineOut)
def get_medicine(medicine_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    m = db.get(Medicine, medicine_id)
    if not m:
        raise not_found("Medicine")
    return m


def _barcode_taken(db: Session, barcode: str | None, exclude_id: int | None = None) -> bool:
    if not barcode:
        return False
    q = select(Medicine.id).where(Medicine.barcode == barcode)
    if exclude_id:
        q = q.where(Medicine.id != exclude_id)
    return db.scalar(q) is not None


@router.post("", response_model=MedicineOut, status_code=201)
def create_medicine(body: MedicineIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    data = body.model_dump()
    data["barcode"] = (data["barcode"] or "").strip() or None
    if _barcode_taken(db, data["barcode"]):
        raise AppError(409, "A medicine with this barcode already exists")
    m = Medicine(**data)
    db.add(m)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "A medicine with this barcode already exists")
    log_action(db, user.id, "CREATE_MEDICINE", "medicine", m.id, f"Created medicine '{m.medicine_name}'")
    refresh_alerts(db)  # a new medicine without batches is OUT_OF_STOCK immediately
    db.commit()
    return m


@router.put("/{medicine_id}", response_model=MedicineOut)
def update_medicine(medicine_id: int, body: MedicineUpdate, user: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    m = db.get(Medicine, medicine_id)
    if not m:
        raise not_found("Medicine")
    changes = body.model_dump(exclude_unset=True)
    if "barcode" in changes:
        changes["barcode"] = (changes["barcode"] or "").strip() or None
        if _barcode_taken(db, changes["barcode"], m.id):
            raise AppError(409, "A medicine with this barcode already exists")
    for key in ("medicine_name", "reorder_level", "prescription_required"):
        if key in changes and changes[key] is None:
            del changes[key]  # non-nullable columns
    for k, v in changes.items():
        setattr(m, k, v)
    log_action(db, user.id, "UPDATE_MEDICINE", "medicine", m.id,
               f"Updated '{m.medicine_name}': {', '.join(sorted(changes)) or 'no changes'}")
    refresh_alerts(db)
    db.commit()
    return m


@router.delete("/{medicine_id}")
def delete_medicine(medicine_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.get(Medicine, medicine_id)
    if not m:
        raise not_found("Medicine")
    has_batches = db.scalar(select(Batch.id).where(Batch.medicine_id == m.id).limit(1))
    has_sales = db.scalar(select(TransactionItem.id).where(TransactionItem.medicine_id == m.id).limit(1))
    if has_batches or has_sales:
        raise AppError(409, "Cannot delete: this medicine has batches or sales history")
    name = m.medicine_name
    # detach any prescription lines pointing at it so the FK cannot block the delete
    for it in db.scalars(select(PrescriptionItem).where(PrescriptionItem.medicine_id == m.id)):
        it.medicine_id = None
    from ..models import Alert
    for a in db.scalars(select(Alert).where(Alert.medicine_id == m.id)):
        db.delete(a)
    db.delete(m)
    log_action(db, user.id, "DELETE_MEDICINE", "medicine", medicine_id, f"Deleted medicine '{name}'")
    db.commit()
    return {"message": f"Medicine '{name}' deleted"}
