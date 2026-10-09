from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models import (AuditLog, Batch, ItemStatus, Medicine, Prescription, PrescriptionItem,
                        Role, RxStatus, User)
from app.security import hash_password

PASSWORD = "Passw0rd!x"


def make_user(sf, username="pharma", role=Role.PHARMACIST, approved=True):
    with sf() as db:
        u = User(name=username.title(), username=username, email=f"{username}@test.io",
                 password_hash=hash_password(PASSWORD), role=role.value, is_active=True, is_approved=approved)
        db.add(u)
        db.commit()
        return u.id


def auth_headers(client, username):
    r = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def login_as(client, sf, username="pharma", role=Role.PHARMACIST):
    make_user(sf, username, role)
    return auth_headers(client, username)


def make_medicine(sf, name, generic=None, composition=None, brand=None, strength=None, reorder=15):
    with sf() as db:
        m = Medicine(medicine_name=name, generic_name=generic, composition=composition, brand_name=brand,
                     strength=strength, reorder_level=reorder)
        db.add(m)
        db.commit()
        return m.id


def add_batch(sf, medicine_id, qty, days_to_expiry, price="2.00", number=None):
    with sf() as db:
        b = Batch(medicine_id=medicine_id, batch_number=number or f"B{medicine_id}-{days_to_expiry}",
                  quantity=qty, expiry_date=date.today() + timedelta(days=days_to_expiry),
                  purchase_price=Decimal("1.00"), selling_price=Decimal(price))
        db.add(b)
        db.commit()
        return b.id


def make_prescription(sf, user_id, items, status=RxStatus.VERIFIED, number="RX-TESTTESTTEST"):
    """items: list of (medicine_id, quantity, ItemStatus)."""
    with sf() as db:
        rx = Prescription(prescription_number=number, patient_reference="P-1", doctor_name="Dr Test",
                          image_path="x.png", status=status.value, created_by=user_id)
        for mid, qty, st in items:
            rx.items.append(PrescriptionItem(medicine_id=mid, extracted_medicine_name="x", quantity=qty,
                                             verification_status=st.value))
        db.add(rx)
        db.commit()
        return rx.id


def batch_qty(sf, batch_id):
    with sf() as db:
        return db.get(Batch, batch_id).quantity


def rx_status(sf, rx_id):
    with sf() as db:
        return db.get(Prescription, rx_id).status


def audit_actions(sf):
    with sf() as db:
        return [(a.action, a.user_id, a.description) for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]


V, R = ItemStatus.VERIFIED, ItemStatus.REJECTED
