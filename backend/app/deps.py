from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .errors import AppError
from .models import Role, User
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def _user_from_token(token: str, db: Session) -> User:
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise AppError(401, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise AppError(401, "User no longer exists")
    if not user.is_active:
        raise AppError(403, "Account is disabled")
    if not user.is_approved:
        raise AppError(403, "Account is pending admin approval")
    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return _user_from_token(token, db)


def get_optional_user(token: str | None = Depends(oauth2_optional),
                      db: Session = Depends(get_db)) -> User | None:
    return _user_from_token(token, db) if token else None


def require_staff(user: User = Depends(get_current_user)) -> User:
    """Logged-in pharmacist or admin."""
    if user.role not in (Role.ADMIN, Role.PHARMACIST):
        raise AppError(403, "Pharmacist or admin access required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN:
        raise AppError(403, "Admin access required")
    return user
