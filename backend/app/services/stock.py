"""Stock rules. Usable stock ALWAYS means: quantity > 0 AND expiry_date >= today."""
from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..models import Batch


def today() -> date:
    return date.today()


def usable_clause(on: date | None = None):
    return and_(Batch.quantity > 0, Batch.expiry_date >= (on or today()))


def usable_stock_map(db: Session) -> dict[int, int]:
    rows = db.execute(select(Batch.medicine_id, func.sum(Batch.quantity))
                      .where(usable_clause()).group_by(Batch.medicine_id)).all()
    return {mid: int(q) for mid, q in rows}


def total_stock_map(db: Session) -> dict[int, int]:
    rows = db.execute(select(Batch.medicine_id, func.sum(Batch.quantity))
                      .group_by(Batch.medicine_id)).all()
    return {mid: int(q or 0) for mid, q in rows}


def usable_stock(db: Session, medicine_id: int) -> int:
    q = db.scalar(select(func.coalesce(func.sum(Batch.quantity), 0))
                  .where(Batch.medicine_id == medicine_id, usable_clause()))
    return int(q or 0)


def usable_batches(db: Session, medicine_id: int, lock: bool = False) -> list[Batch]:
    """Usable batches in FEFO order (earliest expiry first, id as tie-break).
    lock=True issues SELECT ... FOR UPDATE (row locks on PostgreSQL; a no-op on SQLite)."""
    stmt = (select(Batch).where(Batch.medicine_id == medicine_id, usable_clause())
            .order_by(Batch.expiry_date, Batch.id))
    if lock:
        stmt = stmt.with_for_update()
    return list(db.scalars(stmt))
