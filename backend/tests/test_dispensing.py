from decimal import Decimal

from sqlalchemy import func, select

from app.models import RxStatus, Transaction, TransactionItem
from tests.helpers import (V, add_batch, audit_actions, batch_qty, login_as, make_medicine, make_prescription,
                           make_user, rx_status)


def _setup(client, sf):
    h = login_as(client, sf)
    uid = 1
    dolo = make_medicine(sf, "Dolo 500", "Paracetamol", "Paracetamol 500 mg")
    met = make_medicine(sf, "Metformin 500", "Metformin", "Metformin 500 mg")
    return h, uid, dolo, met


def test_dispense_requires_login(client):
    assert client.post("/transactions", json={"prescription_id": 1, "confirmed_dispensing": True}).status_code == 401


def test_refuses_without_confirmation(client, session_factory):
    h, uid, dolo, _ = _setup(client, session_factory)
    b = add_batch(session_factory, dolo, 50, 200)
    rx = make_prescription(session_factory, uid, [(dolo, 10, V)])
    for body in ({"prescription_id": rx}, {"prescription_id": rx, "confirmed_dispensing": False}):
        r = client.post("/transactions", json=body, headers=h)
        assert r.status_code == 422
    assert batch_qty(session_factory, b) == 50
    assert rx_status(session_factory, rx) == "VERIFIED"


def test_refuses_when_prescription_not_verified(client, session_factory):
    h, uid, dolo, _ = _setup(client, session_factory)
    b = add_batch(session_factory, dolo, 50, 200)
    for n, st in enumerate((RxStatus.UPLOADED, RxStatus.PROCESSED, RxStatus.REJECTED)):
        rx = make_prescription(session_factory, uid, [(dolo, 5, V)], status=st, number=f"RX-NOTVERIF{n:04d}")
        r = client.post("/transactions", json={"prescription_id": rx, "confirmed_dispensing": True}, headers=h)
        assert r.status_code == 409, st
    assert batch_qty(session_factory, b) == 50
    assert client.post("/transactions", json={"prescription_id": 9999, "confirmed_dispensing": True},
                       headers=h).status_code == 404


def test_short_stock_is_refused_and_everything_rolls_back(client, session_factory):
    h, uid, dolo, met = _setup(client, session_factory)
    b1 = add_batch(session_factory, dolo, 50, 200)
    b2 = add_batch(session_factory, met, 4, 200)
    rx = make_prescription(session_factory, uid, [(dolo, 10, V), (met, 9, V)])  # 2nd line is short
    r = client.post("/transactions", json={"prescription_id": rx, "confirmed_dispensing": True}, headers=h)
    assert r.status_code == 409
    assert r.json()["detail"] == "Insufficient usable stock for Metformin 500"
    # the first line had already been deducted inside the transaction; it must be undone
    assert batch_qty(session_factory, b1) == 50 and batch_qty(session_factory, b2) == 4
    assert rx_status(session_factory, rx) == "VERIFIED"
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Transaction)) == 0
        assert db.scalar(select(func.count()).select_from(TransactionItem)) == 0
    assert not [a for a in audit_actions(session_factory) if a[0] == "DISPENSE"]


def test_totals_receipt_and_audit_log(client, session_factory):  # test #6
    h, uid, dolo, met = _setup(client, session_factory)
    add_batch(session_factory, dolo, 50, 200, price="2.00")
    add_batch(session_factory, met, 30, 200, price="1.50")
    rx = make_prescription(session_factory, uid, [(dolo, 10, V), (met, 4, V)])
    r = client.post("/transactions", headers=h,
                    json={"prescription_id": rx, "confirmed_dispensing": True, "discount": "1.50", "tax": "0.90"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert Decimal(t["subtotal"]) == Decimal("26.00")      # 10*2.00 + 4*1.50
    assert Decimal(t["discount"]) == Decimal("1.50")
    assert Decimal(t["tax"]) == Decimal("0.90")
    assert Decimal(t["total_amount"]) == Decimal("25.40")   # 26.00 - 1.50 + 0.90
    assert t["pharmacist_username"] == "pharma"
    assert [i["quantity"] for i in t["items"]] == [10, 4]
    assert rx_status(session_factory, rx) == "DISPENSED"
    audit = [a for a in audit_actions(session_factory) if a[0] == "DISPENSE"]
    assert len(audit) == 1 and audit[0][1] == uid and "25.40" in audit[0][2]
    # history endpoints
    assert client.get(f"/transactions/{t['id']}", headers=h).json()["pharmacist_username"] == "pharma"
    assert len(client.get("/transactions?limit=10&offset=0", headers=h).json()) == 1


def test_can_only_dispense_once(client, session_factory):
    h, uid, dolo, _ = _setup(client, session_factory)
    b = add_batch(session_factory, dolo, 50, 200)
    rx = make_prescription(session_factory, uid, [(dolo, 10, V)])
    body = {"prescription_id": rx, "confirmed_dispensing": True}
    assert client.post("/transactions", json=body, headers=h).status_code == 201
    assert client.post("/transactions", json=body, headers=h).status_code == 409
    assert batch_qty(session_factory, b) == 40


def test_discount_and_tax_validation(client, session_factory):
    h, uid, dolo, _ = _setup(client, session_factory)
    b = add_batch(session_factory, dolo, 50, 200, price="2.00")
    rx = make_prescription(session_factory, uid, [(dolo, 5, V)])  # subtotal 10.00
    base = {"prescription_id": rx, "confirmed_dispensing": True}
    assert client.post("/transactions", json={**base, "discount": "10.01"}, headers=h).status_code == 422
    assert client.post("/transactions", json={**base, "discount": "-1"}, headers=h).status_code == 422
    assert client.post("/transactions", json={**base, "tax": "-0.5"}, headers=h).status_code == 422
    assert batch_qty(session_factory, b) == 50          # discount > subtotal was detected AFTER deducting: rolled back
    assert rx_status(session_factory, rx) == "VERIFIED"
    assert client.post("/transactions", json={**base, "discount": "10.00"}, headers=h).status_code == 201


def test_fefo_drains_earliest_expiry_first_and_skips_expired(client, session_factory):  # test #9
    h, uid, dolo, _ = _setup(client, session_factory)
    late = add_batch(session_factory, dolo, 5, 300, price="3.00", number="LATE")
    early = add_batch(session_factory, dolo, 5, 20, price="2.00", number="EARLY")
    expired = add_batch(session_factory, dolo, 100, -5, price="1.00", number="EXPIRED")
    rx = make_prescription(session_factory, uid, [(dolo, 7, V)])
    r = client.post("/transactions", json={"prescription_id": rx, "confirmed_dispensing": True}, headers=h)
    assert r.status_code == 201, r.text
    lines = [(i["batch_number"], i["quantity"], i["unit_price"]) for i in r.json()["items"]]
    assert lines == [("EARLY", 5, "2.00"), ("LATE", 2, "3.00")]   # per-batch lines at each batch's own price
    assert Decimal(r.json()["subtotal"]) == Decimal("16.00")
    assert batch_qty(session_factory, early) == 0
    assert batch_qty(session_factory, late) == 3
    assert batch_qty(session_factory, expired) == 100             # never touched


def test_expired_stock_does_not_count(client, session_factory):
    h, uid, dolo, _ = _setup(client, session_factory)
    expired = add_batch(session_factory, dolo, 100, -1)
    rx = make_prescription(session_factory, uid, [(dolo, 1, V)])
    r = client.post("/transactions", json={"prescription_id": rx, "confirmed_dispensing": True}, headers=h)
    assert r.status_code == 409 and "Insufficient usable stock" in r.json()["detail"]
    assert batch_qty(session_factory, expired) == 100


def test_two_lines_for_same_medicine_cannot_oversell(client, session_factory):
    h, uid, dolo, _ = _setup(client, session_factory)
    b = add_batch(session_factory, dolo, 10, 100)
    rx = make_prescription(session_factory, uid, [(dolo, 6, V), (dolo, 6, V)])  # 12 > 10 in total
    r = client.post("/transactions", json={"prescription_id": rx, "confirmed_dispensing": True}, headers=h)
    assert r.status_code == 409
    assert batch_qty(session_factory, b) == 10
