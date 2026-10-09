from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_staff
from ..errors import not_found
from ..models import Batch, Medicine, Supplier, User
from ..schemas import BatchOut, BatchUpdate, StockIn
from ..services.alerts import refresh_alerts
from ..services.audit import log_action
from ..services.stock import today, total_stock_map, usable_stock_map

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _row(m: Medicine, usable: int, total: int) -> dict:
    return {"medicine_id": m.id, "medicine_name": m.medicine_name, "brand_name": m.brand_name,
            "generic_name": m.generic_name, "strength": m.strength, "dosage_form": m.dosage_form,
            "rack_location": m.rack_location, "shelf_number": m.shelf_number,
            "reorder_level": m.reorder_level, "usable_units": usable, "total_units": total,
            "low_stock": usable <= m.reorder_level, "out_of_stock": usable == 0}


def batch_out(b: Batch) -> BatchOut:
    t = today()
    out = BatchOut.model_validate(b)
    out.medicine_name = b.medicine.medicine_name if b.medicine else None
    out.is_expired = b.expiry_date < t
    out.is_usable = b.quantity > 0 and b.expiry_date >= t
    return out


@router.get("")
def list_inventory(low_only: bool = False, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    usable, total = usable_stock_map(db), total_stock_map(db)
    rows = [_row(m, usable.get(m.id, 0), total.get(m.id, 0))
            for m in db.scalars(select(Medicine).order_by(Medicine.medicine_name))]
    return [r for r in rows if r["low_stock"]] if low_only else rows


# static paths must be declared before "/{medicine_id}"
@router.get("/batches", response_model=list[BatchOut])
def list_all_batches(limit: int = Query(500, ge=1, le=2000), _: User = Depends(require_staff),
                     db: Session = Depends(get_db)):
    stmt = (select(Batch).options(joinedload(Batch.medicine))
            .order_by(Batch.expiry_date, Batch.id).limit(limit))
    return [batch_out(b) for b in db.scalars(stmt)]


@router.get("/batches/{medicine_id}", response_model=list[BatchOut])
def list_batches(medicine_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    if not db.get(Medicine, medicine_id):
        raise not_found("Medicine")
    stmt = (select(Batch).options(joinedload(Batch.medicine))
            .where(Batch.medicine_id == medicine_id).order_by(Batch.expiry_date, Batch.id))
    return [batch_out(b) for b in db.scalars(stmt)]


@router.post("/stock", response_model=BatchOut, status_code=201)
def add_stock(body: StockIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    m = db.get(Medicine, body.medicine_id)
    if not m:
        raise not_found("Medicine")
    if body.supplier_id and not db.get(Supplier, body.supplier_id):
        raise not_found("Supplier")
    data = body.model_dump(exclude_none=True)
    b = Batch(**data)
    db.add(b)
    db.flush()
    log_action(db, user.id, "ADD_STOCK", "batch", b.id,
               f"Added {b.quantity} units of '{m.medicine_name}' batch {b.batch_number} (exp {b.expiry_date})")
    refresh_alerts(db)
    db.commit()
    return batch_out(b)


@router.put("/batch/{batch_id}", response_model=BatchOut)
def update_batch(batch_id: int, body: BatchUpdate, user: User = Depends(require_staff),
                 db: Session = Depends(get_db)):
    b = db.get(Batch, batch_id, options=[joinedload(Batch.medicine)])
    if not b:
        raise not_found("Batch")
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items()
               if v is not None or k in ("supplier_id", "reorder_level", "barcode")}
    if "supplier_id" in changes and changes["supplier_id"] and not db.get(Supplier, changes["supplier_id"]):
        raise not_found("Supplier")
    before = {k: getattr(b, k) for k in changes}
    for k, v in changes.items():
        setattr(b, k, v)
    diff = ", ".join(f"{k}: {before[k]} -> {changes[k]}" for k in changes if before[k] != changes[k])
    log_action(db, user.id, "UPDATE_BATCH", "batch", b.id,
               f"Updated batch {b.batch_number} of '{b.medicine.medicine_name}'" + (f" ({diff})" if diff else ""))
    refresh_alerts(db)
    db.commit()
    return batch_out(b)


@router.get("/{medicine_id}")
def get_inventory(medicine_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    m = db.get(Medicine, medicine_id)
    if not m:
        raise not_found("Medicine")
    usable, total = usable_stock_map(db), total_stock_map(db)
    return _row(m, usable.get(m.id, 0), total.get(m.id, 0))
