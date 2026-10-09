from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, AlertType, Batch, Medicine, Severity
from .stock import today, usable_stock_map


def refresh_alerts(db: Session) -> dict:
    """Recompute stock/expiry alerts. Creates missing unread alerts and marks unread alerts whose
    condition no longer holds as read (resolved). Does NOT commit; the caller owns the transaction."""
    t = today()
    soon = t + timedelta(days=settings.EXPIRY_WARNING_DAYS)
    usable = usable_stock_map(db)
    desired: dict[tuple, tuple[str, str]] = {}

    for m in db.scalars(select(Medicine)):
        u = usable.get(m.id, 0)
        if u == 0:
            desired[(AlertType.OUT_OF_STOCK, m.id, None)] = (
                Severity.CRITICAL, f"{m.medicine_name} is out of stock (no usable units).")
        elif u <= m.reorder_level:
            desired[(AlertType.LOW_STOCK, m.id, None)] = (
                Severity.WARNING, f"{m.medicine_name} is low: {u} usable units (reorder level {m.reorder_level}).")

    for b, name in db.execute(select(Batch, Medicine.medicine_name).join(Medicine).where(Batch.quantity > 0)):
        if b.expiry_date < t:
            desired[(AlertType.EXPIRED, b.medicine_id, b.id)] = (
                Severity.CRITICAL, f"{name} batch {b.batch_number} expired on {b.expiry_date} ({b.quantity} units).")
        elif b.expiry_date <= soon:
            days = (b.expiry_date - t).days
            sev = Severity.CRITICAL if days <= 30 else Severity.WARNING
            desired[(AlertType.EXPIRING_SOON, b.medicine_id, b.id)] = (
                sev, f"{name} batch {b.batch_number} expires in {days} days ({b.quantity} units).")

    existing = {(a.alert_type, a.medicine_id, a.batch_id): a
                for a in db.scalars(select(Alert).where(Alert.is_read.is_(False)))}
    created = resolved = 0
    for key, (sev, msg) in desired.items():
        if key not in existing:
            db.add(Alert(alert_type=key[0].value, medicine_id=key[1], batch_id=key[2],
                         message=msg, severity=sev.value))
            created += 1
    for key, alert in existing.items():
        if key not in desired:
            alert.is_read = True
            resolved += 1
    db.flush()
    return {"created": created, "resolved": resolved, "active": len(desired)}
