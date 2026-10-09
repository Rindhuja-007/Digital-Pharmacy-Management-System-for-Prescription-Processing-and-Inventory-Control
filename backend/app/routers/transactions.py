from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..database import get_db
from ..deps import require_staff
from ..errors import not_found
from ..models import Transaction, TransactionItem, User
from ..schemas import DispenseIn, ReceiptOut
from ..services.dispensing import dispense, receipt_dict

router = APIRouter(prefix="/transactions", tags=["transactions"])

_LOAD = (joinedload(Transaction.pharmacist), joinedload(Transaction.prescription),
         selectinload(Transaction.items).selectinload(TransactionItem.medicine),
         selectinload(Transaction.items).selectinload(TransactionItem.batch))


@router.post("", response_model=ReceiptOut, status_code=201)
def create_transaction(body: DispenseIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    tx = dispense(db, body.prescription_id, user, body.confirmed_dispensing, body.discount, body.tax)
    return receipt_dict(tx)


@router.get("", response_model=list[ReceiptOut])
def list_transactions(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                      _: User = Depends(require_staff), db: Session = Depends(get_db)):
    stmt = select(Transaction).options(*_LOAD).order_by(Transaction.id.desc()).limit(limit).offset(offset)
    return [receipt_dict(t) for t in db.scalars(stmt).unique()]


@router.get("/{transaction_id}", response_model=ReceiptOut)
def get_transaction(transaction_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    tx = db.scalar(select(Transaction).where(Transaction.id == transaction_id).options(*_LOAD))
    if not tx:
        raise not_found("Transaction")
    return receipt_dict(tx)
