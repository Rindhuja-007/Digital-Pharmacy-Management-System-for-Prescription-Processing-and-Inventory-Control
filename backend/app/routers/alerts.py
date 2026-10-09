from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_staff
from ..errors import not_found
from ..models import Alert, User
from ..schemas import AlertOut
from ..services.alerts import refresh_alerts

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(unread_only: bool = False, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    stmt = select(Alert).order_by(Alert.is_read, Alert.created_at.desc(), Alert.id.desc())
    if unread_only:
        stmt = stmt.where(Alert.is_read.is_(False))
    return list(db.scalars(stmt.limit(500)))


@router.post("/refresh")
def refresh(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    result = refresh_alerts(db)
    db.commit()
    return result


@router.put("/{alert_id}/read", response_model=AlertOut)
def mark_read(alert_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if not a:
        raise not_found("Alert")
    a.is_read = True
    db.commit()
    return a
