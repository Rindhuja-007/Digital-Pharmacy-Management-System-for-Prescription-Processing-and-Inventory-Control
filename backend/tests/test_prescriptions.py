import re

import cv2
import numpy as np
import pytest
from sqlalchemy import func, select

from app.models import Role, Transaction
from tests.helpers import add_batch, audit_actions, batch_qty, login_as, make_medicine, rx_status


def png_bytes(w=400, h=300, ext=".png"):
    img = np.full((h, w, 3), 255, np.uint8)
    cv2.putText(img, "Tab Dolo 500", (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    ok, buf = cv2.imencode(ext, img)
    assert ok
    return buf.tobytes()


def upload(client, h, data=None, name="rx.png", ctype="image/png", **form):
    return client.post("/prescriptions/upload", headers=h, files={"file": (name, data or png_bytes(), ctype)},
                       data={"patient_reference": "PT-100", "doctor_name": "Dr. Rao", **form})


def run_to_match(client, h, ocr_stub, text):
    ocr_stub.text = text
    rx = upload(client, h).json()["id"]
    assert client.post(f"/prescriptions/{rx}/process", headers=h).status_code == 200
    ex = client.post(f"/prescriptions/{rx}/extract", headers=h)
    assert ex.status_code == 200, ex.text
    m = client.post(f"/prescriptions/{rx}/match", headers=h)
    assert m.status_code == 200, m.text
    return rx, m.json()["matches"]


@pytest.fixture()
def seeded(client, session_factory):
    """Seeded demo catalogue: Crocin (0 stock), Dolo (120), Metformin (80) + a pharmacist."""
    client.post("/auth/seed-demo")
    r = client.post("/auth/login", json={"username": "pharmacist", "password": "Pharmacist@123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------- upload / safety rule 1
def test_upload_accepts_jpg_and_png_and_creates_uploaded_prescription(client, session_factory):
    h = login_as(client, session_factory)
    for data, name, ctype in ((png_bytes(), "a.png", "image/png"), (png_bytes(ext=".jpg"), "a.jpg", "image/jpeg")):
        r = upload(client, h, data, name, ctype)
        assert r.status_code == 201, r.text
        body = r.json()
        assert re.fullmatch(r"RX-[0-9A-F]{12}", body["prescription_number"])
        assert body["status"] == "UPLOADED" and body["items"] == [] and body["patient_reference"] == "PT-100"
    assert "UPLOAD_PRESCRIPTION" in [a[0] for a in audit_actions(session_factory)]


@pytest.mark.parametrize("data,name,ctype", [
    (b"GIF89a....", "a.gif", "image/gif"),
    (b"just text", "a.png", "image/png"),            # wrong magic bytes
    (b"%PDF-1.4", "a.pdf", "application/pdf"),
    (b"\x89PNG\r\n\x1a\nbroken", "a.png", "image/png"),   # right magic, not decodable
])
def test_upload_rejects_non_images(client, session_factory, data, name, ctype):
    h = login_as(client, session_factory)
    assert upload(client, h, data, name, ctype).status_code == 422
    assert client.get("/prescriptions", headers=h).json() == []


def test_upload_ocr_extract_match_never_approve_or_touch_stock(client, session_factory, ocr_stub, seeded):  # rule 1
    before = {r["medicine_name"]: r["total_units"] for r in client.get("/inventory", headers=seeded).json()}
    rx, _ = run_to_match(client, seeded, ocr_stub, "Tab Dolo 500 mg 1-0-1 x 5 days")
    detail = client.get(f"/prescriptions/{rx}", headers=seeded).json()
    assert detail["status"] == "PROCESSED" and detail["confidence_score"] == 93.5
    assert [i["verification_status"] for i in detail["items"]] == ["PENDING"]
    after = {r["medicine_name"]: r["total_units"] for r in client.get("/inventory", headers=seeded).json()}
    assert before == after
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Transaction)) == 0
    # a PENDING (matched but unverified) prescription cannot be dispensed
    r = client.post("/transactions", headers=seeded, json={"prescription_id": rx, "confirmed_dispensing": True})
    assert r.status_code == 409


def test_preprocess_runs_opencv_and_serves_images(client, session_factory):
    h = login_as(client, session_factory)
    rx = upload(client, h, png_bytes(w=2600, h=1800)).json()["id"]
    assert client.get(f"/prescriptions/{rx}/image?kind=processed", headers=h).status_code == 404
    r = client.post(f"/prescriptions/{rx}/preprocess", headers=h)
    assert r.status_code == 200 and r.json()["has_processed_image"] is True and r.json()["status"] == "UPLOADED"
    img = client.get(f"/prescriptions/{rx}/image?kind=processed", headers=h)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    arr = cv2.imdecode(np.frombuffer(img.content, np.uint8), cv2.IMREAD_UNCHANGED)
    assert arr.shape[1] == 1800 and arr.ndim == 2 and set(np.unique(arr)) <= {0, 255}   # resized, grayscale, binary
    assert client.get(f"/prescriptions/{rx}/image", headers=h).status_code == 200
    assert client.get(f"/prescriptions/{rx}/image").status_code == 401


def test_ocr_uses_processed_image_when_available(client, session_factory, monkeypatch):
    from app.services import ocr
    seen = []
    monkeypatch.setattr(ocr, "run_ocr", lambda p: (seen.append(str(p)) or ("Tab X", 50.0)))
    h = login_as(client, session_factory)
    rx = upload(client, h).json()["id"]
    client.post(f"/prescriptions/{rx}/process", headers=h)
    client.post(f"/prescriptions/{rx}/preprocess", headers=h)
    client.post(f"/prescriptions/{rx}/process", headers=h)
    assert not seen[0].endswith("_processed.png") and seen[1].endswith("_processed.png")


def test_extract_requires_ocr_first_and_reports_skipped_lines(client, session_factory, ocr_stub):
    h = login_as(client, session_factory)
    rx = upload(client, h).json()["id"]
    assert client.post(f"/prescriptions/{rx}/extract", headers=h).status_code == 409
    ocr_stub.text = "Dr. Rao MBBS\nTab Telma 40 mg OD for BP\nTab Dolo 500 mg BD"
    client.post(f"/prescriptions/{rx}/process", headers=h)
    r = client.post(f"/prescriptions/{rx}/extract", headers=h).json()
    assert [i["extracted_medicine_name"] for i in r["prescription"]["items"]] == ["Dolo 500 mg"]
    assert [s["line"] for s in r["skipped_lines"]] == ["Tab Telma 40 mg OD for BP"]


# ---------------------------------------------------------------- test #3
def test_out_of_stock_brand_surfaces_in_stock_substitute_and_dispense_records_pharmacist(
        client, session_factory, ocr_stub, seeded):
    rx, matches = run_to_match(client, seeded, ocr_stub, "Tab Crocin 500 mg BD x 3 days")
    m = matches[0]
    top = m["candidates"][0]
    assert top["medicine_name"] == "Crocin 500" and top["usable_stock"] == 0 and top["level"] == "HIGH"
    subs = m["substitutes"]
    assert subs[0]["medicine_name"] == "Dolo 500" and subs[0]["usable_stock"] == 120   # in-stock first
    assert "paracetamol" in subs[0]["shared_ingredients"]
    assert all(s["medicine_name"] != "Metformin 500" for s in subs)                      # different salt

    item = client.get(f"/prescriptions/{rx}", headers=seeded).json()["items"][0]
    dolo = subs[0]["medicine_id"]
    v = client.put(f"/prescriptions/{rx}/verify", headers=seeded, json={"decisions": [
        {"item_id": item["id"], "decision": "VERIFIED", "medicine_id": dolo, "quantity": 6}]})
    assert v.status_code == 200 and v.json()["status"] == "VERIFIED" and v.json()["verified_by"] is not None
    tx = client.post("/transactions", headers=seeded, json={"prescription_id": rx, "confirmed_dispensing": True})
    assert tx.status_code == 201, tx.text
    assert tx.json()["pharmacist_username"] == "pharmacist"
    assert tx.json()["items"][0]["medicine_name"] == "Dolo 500" and tx.json()["items"][0]["quantity"] == 6
    stock = {r["medicine_name"]: r["usable_units"] for r in client.get("/inventory", headers=seeded).json()}
    assert stock["Dolo 500"] == 114
    assert rx_status(session_factory, rx) == "DISPENSED"


# ---------------------------------------------------------------- test #4 and #5
TWO_LINES = "Tab Dolo 500 mg 1-0-1 x 5 days\nTab Metformin 500 mg BD x 10 days"


def test_mixed_verification_gives_verified_and_availability_counts_only_verified(client, session_factory,
                                                                                 ocr_stub, seeded):
    rx, matches = run_to_match(client, seeded, ocr_stub, TWO_LINES)
    items = client.get(f"/prescriptions/{rx}", headers=seeded).json()["items"]
    dolo_id = matches[0]["candidates"][0]["medicine_id"]
    body = {"decisions": [
        {"item_id": items[0]["id"], "decision": "VERIFIED", "medicine_id": dolo_id, "quantity": 10},
        {"item_id": items[1]["id"], "decision": "REJECTED"}]}
    r = client.put(f"/prescriptions/{rx}/verify", headers=seeded, json=body)
    assert r.status_code == 200 and r.json()["status"] == "VERIFIED"
    assert [i["verification_status"] for i in r.json()["items"]] == ["VERIFIED", "REJECTED"]
    av = client.post(f"/prescriptions/{rx}/availability", headers=seeded).json()
    assert len(av["items"]) == 1 and av["items"][0]["medicine_name"] == "Dolo 500"
    assert av["items"][0]["needed"] == 10 and av["items"][0]["available"] == 120 and av["items"][0]["shortage"] == 0
    assert av["can_dispense"] is True and av["items"][0]["batches"][0]["quantity"] == 120
    tx = client.post("/transactions", headers=seeded, json={"prescription_id": rx, "confirmed_dispensing": True})
    assert len(tx.json()["items"]) == 1                                     # rejected line never dispensed
    stock = {r["medicine_name"]: r["usable_units"] for r in client.get("/inventory", headers=seeded).json()}
    assert stock["Metformin 500"] == 80


def test_availability_reports_shortage_and_does_not_double_count_shared_stock(client, session_factory, ocr_stub, seeded):
    rx, matches = run_to_match(client, seeded, ocr_stub, "Tab Dolo 500 mg OD\nTab Dolo 500 mg BD")
    items = client.get(f"/prescriptions/{rx}", headers=seeded).json()["items"]
    dolo = matches[0]["candidates"][0]["medicine_id"]
    client.put(f"/prescriptions/{rx}/verify", headers=seeded, json={"decisions": [
        {"item_id": items[0]["id"], "decision": "VERIFIED", "medicine_id": dolo, "quantity": 100},
        {"item_id": items[1]["id"], "decision": "VERIFIED", "medicine_id": dolo, "quantity": 50}]})
    av = client.post(f"/prescriptions/{rx}/availability", headers=seeded).json()
    assert [(i["available"], i["shortage"]) for i in av["items"]] == [(120, 0), (20, 30)]   # 120 total, not 120 twice
    assert av["can_dispense"] is False


def test_verify_with_quantity_zero_or_less_is_422_and_changes_nothing(client, session_factory, ocr_stub, seeded):
    rx, matches = run_to_match(client, seeded, ocr_stub, "Tab Dolo 500 mg BD x 5 days")
    item = client.get(f"/prescriptions/{rx}", headers=seeded).json()["items"][0]
    dolo = matches[0]["candidates"][0]["medicine_id"]
    for qty in (0, -3, None):
        r = client.put(f"/prescriptions/{rx}/verify", headers=seeded, json={"decisions": [
            {"item_id": item["id"], "decision": "VERIFIED", "medicine_id": dolo, "quantity": qty}]})
        assert r.status_code == 422, qty
    assert rx_status(session_factory, rx) == "PROCESSED"
    assert client.get(f"/prescriptions/{rx}", headers=seeded).json()["items"][0]["verification_status"] == "PENDING"


def test_verify_validation_rules(client, session_factory, ocr_stub, seeded):
    rx, matches = run_to_match(client, seeded, ocr_stub, TWO_LINES)
    items = client.get(f"/prescriptions/{rx}", headers=seeded).json()["items"]
    dolo = matches[0]["candidates"][0]["medicine_id"]
    put = lambda decisions: client.put(f"/prescriptions/{rx}/verify", headers=seeded, json={"decisions": decisions})
    ok = {"item_id": items[0]["id"], "decision": "VERIFIED", "medicine_id": dolo, "quantity": 2}
    assert put([ok]).status_code == 422                                                       # missing line 2
    assert put([ok, {"item_id": items[1]["id"], "decision": "VERIFIED", "quantity": 1}]).status_code == 422  # no medicine
    assert put([ok, {"item_id": items[1]["id"], "decision": "VERIFIED", "medicine_id": 9999, "quantity": 1}]).status_code == 422
    assert put([ok, ok]).status_code == 422                                                   # duplicate decision
    assert put([ok, {"item_id": 99999, "decision": "REJECTED"}]).status_code == 422           # unknown line
    assert put([ok, {"item_id": items[1]["id"], "decision": "MAYBE"}]).status_code == 422     # bad decision value
    assert put([]).status_code == 422
    assert rx_status(session_factory, rx) == "PROCESSED"


def test_all_rejected_makes_prescription_rejected_and_logs_it(client, session_factory, ocr_stub, seeded):
    rx, _ = run_to_match(client, seeded, ocr_stub, TWO_LINES)
    items = client.get(f"/prescriptions/{rx}", headers=seeded).json()["items"]
    r = client.put(f"/prescriptions/{rx}/verify", headers=seeded,
                   json={"decisions": [{"item_id": i["id"], "decision": "REJECTED"} for i in items]})
    assert r.json()["status"] == "REJECTED"
    assert "REJECT_PRESCRIPTION" in [a[0] for a in audit_actions(session_factory)]
    assert client.post("/transactions", headers=seeded,
                       json={"prescription_id": rx, "confirmed_dispensing": True}).status_code == 409


def test_manual_item_and_dispensed_prescription_is_locked(client, session_factory, ocr_stub, seeded):
    ocr_stub.text = "Dr Someone\nNo medicine lines here"
    rx = upload(client, seeded).json()["id"]
    client.post(f"/prescriptions/{rx}/process", headers=seeded)
    assert client.post(f"/prescriptions/{rx}/extract", headers=seeded).json()["prescription"]["items"] == []
    dolo = [m for m in client.get("/medicines?q=dolo", headers=seeded).json()][0]["id"]
    add = client.post(f"/prescriptions/{rx}/items", headers=seeded, json={
        "extracted_medicine_name": "Dolo 500", "medicine_id": dolo, "quantity": 4, "frequency": "BD"})
    assert add.status_code == 201 and add.json()["verification_status"] == "PENDING"
    assert client.post(f"/prescriptions/{rx}/items", headers=seeded,
                       json={"extracted_medicine_name": "x", "quantity": 0}).status_code == 422
    item = add.json()["id"]
    verify = {"decisions": [{"item_id": item, "decision": "VERIFIED", "medicine_id": dolo, "quantity": 4}]}
    assert client.put(f"/prescriptions/{rx}/verify", headers=seeded, json=verify).status_code == 200
    assert client.post("/transactions", headers=seeded, json={"prescription_id": rx, "confirmed_dispensing": True}).status_code == 201
    assert client.put(f"/prescriptions/{rx}/verify", headers=seeded, json=verify).status_code == 409
    assert client.post(f"/prescriptions/{rx}/items", headers=seeded, json={"extracted_medicine_name": "y"}).status_code == 409
    assert client.post(f"/prescriptions/{rx}/process", headers=seeded).status_code == 409
    assert batch_qty(session_factory, 1) == 116   # Dolo batch: 120 - 4


def test_audit_trail_covers_upload_verify_and_dispense(client, session_factory, ocr_stub, seeded):
    rx, matches = run_to_match(client, seeded, ocr_stub, "Tab Dolo 500 mg BD")
    item = client.get(f"/prescriptions/{rx}", headers=seeded).json()["items"][0]
    client.put(f"/prescriptions/{rx}/verify", headers=seeded, json={"decisions": [
        {"item_id": item["id"], "decision": "VERIFIED", "medicine_id": matches[0]["candidates"][0]["medicine_id"], "quantity": 2}]})
    client.post("/transactions", headers=seeded, json={"prescription_id": rx, "confirmed_dispensing": True})
    actions = [a[0] for a in audit_actions(session_factory)]
    for needed in ("UPLOAD_PRESCRIPTION", "VERIFY_PRESCRIPTION", "DISPENSE"):
        assert needed in actions
    assert all(a[1] is not None for a in audit_actions(session_factory) if a[0] in ("UPLOAD_PRESCRIPTION", "VERIFY_PRESCRIPTION", "DISPENSE"))


def test_prescription_list_and_filter(client, session_factory):
    h = login_as(client, session_factory)
    upload(client, h)
    upload(client, h)
    rows = client.get("/prescriptions", headers=h).json()
    assert len(rows) == 2 and rows[0]["id"] > rows[1]["id"] and "extracted_text" not in rows[0]
    assert client.get("/prescriptions?status=VERIFIED", headers=h).json() == []
    assert client.get("/prescriptions/9999", headers=h).status_code == 404
