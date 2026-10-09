from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user, get_optional_user, require_admin
from ..errors import AppError, not_found
from ..models import AuditLog, Role, User
from ..schemas import LoginIn, RegisterAdminIn, StaffCreateIn, TokenOut, UserOut
from ..security import create_access_token, hash_password, verify_password
from ..services.audit import log_action
from ..services.seed import seed_demo
import hmac

router = APIRouter(prefix="/auth", tags=["auth"])


def _admin_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == Role.ADMIN.value)) or 0


def _check_unique(db: Session, username: str, email: str):
    if db.scalar(select(User).where(or_(User.username == username, User.email == email))):
        raise AppError(409, "Username or email already registered")


def _authenticate(db: Session, username: str, password: str) -> User:
    ident = username.strip().lower()
    user = db.scalar(select(User).where(or_(User.username == ident, User.email == ident)))
    if not user or not verify_password(password, user.password_hash):
        raise AppError(401, "Incorrect username or password")
    if not user.is_approved:
        raise AppError(403, "Account is pending admin approval")
    if not user.is_active:
        raise AppError(403, "Account is disabled")
    return user


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    has_admin = _admin_count(db) > 0
    return {"has_admin": has_admin, "setup_required": not has_admin}


@router.post("/register-admin", response_model=UserOut, status_code=201)
def register_admin(body: RegisterAdminIn, db: Session = Depends(get_db)):
    _check_unique(db, body.username, body.email)
    first = _admin_count(db) == 0
    code = settings.ADMIN_APPROVAL_CODE
    code_ok = bool(code) and body.approval_code is not None and hmac.compare_digest(body.approval_code, code)
    approved = first or code_ok
    user = User(name=body.name, username=body.username, email=body.email,
                password_hash=hash_password(body.password), role=Role.ADMIN.value,
                is_active=True, is_approved=approved)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "Username or email already registered")
    if approved:
        user.approved_by = user.id if first else None
    log_action(db, user.id, "REGISTER_ADMIN", "user", user.id,
               f"Admin '{user.username}' registered ({'approved' if approved else 'pending approval'})")
    db.commit()
    if not approved:
        return JSONResponse(status_code=202, content={
            "message": "Registration received. An existing admin must approve this account before you can sign in.",
            "user": jsonable_encoder(UserOut.model_validate(user))})
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = _authenticate(db, body.username, body.password)
    return TokenOut(access_token=create_access_token(user.id, user.role), user=UserOut.model_validate(user))


@router.post("/token", response_model=TokenOut)
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = _authenticate(db, form.username, form.password)
    return TokenOut(access_token=create_access_token(user.id, user.role), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/staff", response_model=list[UserOut])
def list_staff(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.id)))


@router.post("/staff", response_model=UserOut, status_code=201)
def create_staff(body: StaffCreateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _check_unique(db, body.username, body.email)
    user = User(name=body.name, username=body.username, email=body.email,
                password_hash=hash_password(body.password), role=body.role,
                is_active=True, is_approved=True, approved_by=admin.id)
    db.add(user)
    db.flush()
    log_action(db, admin.id, "CREATE_USER", "user", user.id, f"Created {body.role} '{user.username}'")
    db.commit()
    return user


def _pending_admin(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if not u:
        raise not_found("User")
    if u.is_approved:
        raise AppError(409, "User is already approved")
    return u


@router.post("/approve-admin/{user_id}", response_model=UserOut)
def approve_admin(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = _pending_admin(db, user_id)
    u.is_approved = True
    u.approved_by = admin.id
    log_action(db, admin.id, "APPROVE_ADMIN", "user", u.id, f"Approved admin '{u.username}'")
    db.commit()
    return u


@router.post("/reject-admin/{user_id}")
def reject_admin(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = _pending_admin(db, user_id)
    name = u.username
    # keep the audit trail: detach it from the user row (descriptions still name the account)
    db.execute(update(AuditLog).where(AuditLog.user_id == u.id).values(user_id=None))
    db.delete(u)
    log_action(db, admin.id, "REJECT_ADMIN", "user", user_id, f"Rejected admin registration '{name}'")
    db.commit()
    return {"message": f"Registration for '{name}' rejected"}


@router.delete("/staff/{user_id}")
def delete_staff(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if user_id == admin.id:
        raise AppError(409, "You cannot delete your own account")
    u = db.get(User, user_id)
    if not u:
        raise not_found("User")
    name = u.username
    try:
        with db.begin_nested():
            db.delete(u)
        outcome = "deleted"
    except IntegrityError:  # has prescriptions/audit history: keep the record, disable the login
        u.is_active = False
        outcome = "deactivated (has activity history)"
    log_action(db, admin.id, "DELETE_USER", "user", user_id, f"Account '{name}' {outcome}")
    db.commit()
    return {"message": f"Account '{name}' {outcome}"}


@router.post("/seed-demo")
def seed(db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    """Allowed without a token only on a brand-new database; otherwise admin only."""
    has_users = (db.scalar(select(func.count()).select_from(User)) or 0) > 0
    if has_users and (user is None or user.role != Role.ADMIN):
        raise AppError(403, "Admin access required to seed demo data")
    result = seed_demo(db)
    db.commit()
    return result
