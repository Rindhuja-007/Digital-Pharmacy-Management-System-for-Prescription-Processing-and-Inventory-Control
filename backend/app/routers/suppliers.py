from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_staff
from ..models import Supplier, User
from ..schemas import SupplierIn, SupplierOut
from ..services.audit import log_action

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=list[SupplierOut])
def list_suppliers(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    return list(db.scalars(select(Supplier).order_by(Supplier.name)))


@router.post("", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    s = Supplier(**body.model_dump())
    db.add(s)
    db.flush()
    log_action(db, user.id, "CREATE_SUPPLIER", "supplier", s.id, f"Created supplier '{s.name}'")
    db.commit()
    return s
