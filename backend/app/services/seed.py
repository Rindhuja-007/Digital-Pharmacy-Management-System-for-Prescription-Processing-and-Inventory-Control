from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Batch, Medicine, Role, User
from ..security import hash_password
from .alerts import refresh_alerts
from .stock import today

DEMO_USERS = [
    ("Demo Admin", "admin", "admin@pharmacare.local", "Admin@123", Role.ADMIN),
    ("Demo Pharmacist", "pharmacist", "pharmacist@pharmacare.local", "Pharmacist@123", Role.PHARMACIST),
]

# name, generic, composition, brand, strength, form, stock, selling price
DEMO_MEDICINES = [
    ("Crocin 500", "Paracetamol", "Paracetamol 500 mg", "Crocin", "500 mg", "Tablet", 0, "2.50"),
    ("Dolo 500", "Paracetamol", "Paracetamol 500 mg", "Dolo", "500 mg", "Tablet", 120, "2.00"),
    ("Metformin 500", "Metformin Hydrochloride", "Metformin Hydrochloride 500 mg", "Glycomet", "500 mg",
     "Tablet", 80, "1.50"),
]


def seed_demo(db: Session) -> dict:
    """Idempotent demo data. Does not commit."""
    made_users, made_meds = [], []
    first_admin = None
    for name, username, email, pw, role in DEMO_USERS:
        u = db.scalar(select(User).where(User.username == username))
        if not u:
            u = User(name=name, username=username, email=email, password_hash=hash_password(pw),
                     role=role.value, is_active=True, is_approved=True)
            db.add(u)
            made_users.append(username)
        if role == Role.ADMIN:
            first_admin = u
    db.flush()
    if first_admin and first_admin.approved_by is None:
        first_admin.approved_by = first_admin.id
    for name, generic, comp, brand, strength, form, stock, price in DEMO_MEDICINES:
        if db.scalar(select(Medicine).where(Medicine.medicine_name == name)):
            continue
        m = Medicine(medicine_name=name, generic_name=generic, composition=comp, brand_name=brand,
                     strength=strength, dosage_form=form, unit_of_measure="tablet", pack_size="10 tablets",
                     category="Demo", prescription_required=False, reorder_level=15,
                     rack_location="A1", shelf_number="1", mrp=Decimal(price))
        db.add(m)
        db.flush()
        if stock > 0:
            db.add(Batch(medicine_id=m.id, batch_number=f"DEMO-{m.id:03d}", quantity=stock,
                         expiry_date=today() + timedelta(days=365), purchase_price=Decimal("1.00"),
                         selling_price=Decimal(price)))
        made_meds.append(name)
    db.flush()
    refresh_alerts(db)
    return {"users_created": made_users, "medicines_created": made_meds,
            "credentials": {"admin": "Admin@123", "pharmacist": "Pharmacist@123"}}
