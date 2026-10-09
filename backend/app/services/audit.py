from sqlalchemy.orm import Session

from ..models import AuditLog


def log_action(db: Session, user_id: int | None, action: str, entity_type: str,
               entity_id: int | None, description: str) -> AuditLog:
    """Adds an audit row to the CURRENT transaction (committed/rolled back with the caller's work)."""
    row = AuditLog(user_id=user_id, action=action, entity_type=entity_type,
                   entity_id=entity_id, description=description)
    db.add(row)
    return row
