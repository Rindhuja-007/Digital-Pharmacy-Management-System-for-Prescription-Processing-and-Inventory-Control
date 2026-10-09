from datetime import date, timedelta
from decimal import Decimal

from app.models import Role
from tests.helpers import add_batch, audit_actions, login_as, make_medicine, make_user, auth_headers


def _csv(client, h, text):
    return client.post("/medicines/import-csv", headers=h, files={"file": ("m.csv", text.encode(), "text/csv")})


def test_sample_csv_download_and_import(client, session_factory):  # test #2
    h = login_as(client, session_factory)
    r = client.get("/medicines/sample-csv", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0].startswith("medicine_name,generic_name")

    res = _csv(client, h, r.text)                      # the sample must import cleanly
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created_medicines"] == 3 and body["batches_added"] == 2 and body["errors"] == []
    meds = {m["medicine_name"]: m for m in client.get("/medicines", headers=h).json()}
    assert meds["Dolo 650"]["rack_location"] == "A1" and meds["Amoxicillin 500"]["prescription_required"] is True
    inv = {i["medicine_name"]: i["usable_units"] for i in client.get("/inventory", headers=h).json()}
    assert inv == {"Dolo 650": 200, "Amoxicillin 500": 90, "Metformin 500": 0}

    again = _csv(client, h, r.text).json()             # re-import: nothing duplicated
    assert again["created_medicines"] == 0 and again["skipped_batches"] == 2
    assert len(client.get("/medicines", headers=h).json()) == 3
    assert any(a[0] == "IMPORT_MEDICINES_CSV" for a in audit_actions(session_factory))


def test_csv_updates_rack_location_and_appends_batches_but_keeps_other_fields(client, session_factory):
    h = login_as(client, session_factory)
    mid = make_medicine(session_factory, "Dolo 500", generic="Paracetamol", strength="500 mg")
    exp = (date.today() + timedelta(days=400)).isoformat()
    text = ("medicine_name,strength,generic_name,rack_location,shelf_number,batch_number,quantity,expiry_date,selling_price\n"
            f"Dolo 500,500 mg,SHOULD-NOT-OVERWRITE,Z9,4,N1,25,{exp},2.25\n")
    assert _csv(client, h, text).json()["updated_medicines"] == 1
    m = client.get(f"/medicines/{mid}", headers=h).json()
    assert m["rack_location"] == "Z9" and m["shelf_number"] == "4" and m["generic_name"] == "Paracetamol"
    b = client.get(f"/inventory/batches/{mid}", headers=h).json()
    assert len(b) == 1 and b[0]["quantity"] == 25 and Decimal(b[0]["selling_price"]) == Decimal("2.25")


def test_csv_bad_rows_are_reported_and_good_rows_still_import(client, session_factory):
    h = login_as(client, session_factory)
    text = ("medicine_name,batch_number,quantity,expiry_date,selling_price\n"
            "Good One,G1,10,2030-01-01,1.00\n"
            "Bad Date,B1,10,01/02/2030,1.00\n"
            ",X,1,2030-01-01,1.00\n"
            "Bad Qty,B2,abc,2030-01-01,1.00\n")
    body = _csv(client, h, text).json()
    assert body["created_medicines"] == 1 and body["batches_added"] == 1
    assert [e["row"] for e in body["errors"]] == [3, 4, 5]
    names = [m["medicine_name"] for m in client.get("/medicines", headers=h).json()]
    assert names == ["Good One"]                                  # failed rows left nothing behind
    assert _csv(client, h, "wrong,header\n1,2\n").status_code == 422


def test_medicine_permissions_and_delete_rules(client, session_factory):
    ph = login_as(client, session_factory, "pharma")
    ad = login_as(client, session_factory, "boss", Role.ADMIN)
    r = client.post("/medicines", headers=ph, json={"medicine_name": "Aspirin 75", "barcode": "123"})
    assert r.status_code == 201
    mid = r.json()["id"]
    assert client.post("/medicines", headers=ph, json={"medicine_name": "Other", "barcode": "123"}).status_code == 409
    assert client.put(f"/medicines/{mid}", headers=ph, json={"brand_name": "X"}).status_code == 403
    assert client.delete(f"/medicines/{mid}", headers=ph).status_code == 403
    assert client.put(f"/medicines/{mid}", headers=ad, json={"brand_name": "Ecosprin"}).json()["brand_name"] == "Ecosprin"
    add_batch(session_factory, mid, 10, 100)
    assert client.delete(f"/medicines/{mid}", headers=ad).status_code == 409       # has batches
    other = client.post("/medicines", headers=ph, json={"medicine_name": "Temp"}).json()["id"]
    assert client.delete(f"/medicines/{other}", headers=ad).status_code == 200
    actions = [a[0] for a in audit_actions(session_factory)]
    assert "CREATE_MEDICINE" in actions and "DELETE_MEDICINE" in actions
    assert [m["medicine_name"] for m in client.get("/medicines?q=aspi", headers=ph).json()] == ["Aspirin 75"]


def test_add_stock_batch_update_and_usable_vs_total(client, session_factory):
    h = login_as(client, session_factory)
    mid = make_medicine(session_factory, "Dolo 500")
    body = {"medicine_id": mid, "batch_number": "N1", "quantity": 40, "selling_price": "2.10",
            "expiry_date": (date.today() + timedelta(days=200)).isoformat()}
    r = client.post("/inventory/stock", headers=h, json=body)
    assert r.status_code == 201 and r.json()["is_usable"] is True
    bid = r.json()["id"]
    assert client.post("/inventory/stock", headers=h, json={**body, "quantity": 0}).status_code == 422
    assert client.post("/inventory/stock", headers=h, json={**body, "selling_price": "-1"}).status_code == 422
    assert client.post("/inventory/stock", headers=h, json={**body, "medicine_id": 999}).status_code == 404
    add_batch(session_factory, mid, 60, -3, number="OLD")
    inv = client.get(f"/inventory/{mid}", headers=h).json()
    assert inv["usable_units"] == 40 and inv["total_units"] == 100
    flags = {b["batch_number"]: b["is_expired"] for b in client.get(f"/inventory/batches/{mid}", headers=h).json()}
    assert flags == {"OLD": True, "N1": False}
    r = client.put(f"/inventory/batch/{bid}", headers=h, json={"quantity": 35})
    assert r.json()["quantity"] == 35
    assert client.put(f"/inventory/batch/{bid}", headers=h, json={"quantity": -1}).status_code == 422
    assert [a[0] for a in audit_actions(session_factory)].count("ADD_STOCK") == 1
    assert "UPDATE_BATCH" in [a[0] for a in audit_actions(session_factory)]


def test_out_of_stock_alert_for_medicine_with_no_batches(client, session_factory):  # test #7
    h = login_as(client, session_factory)
    mid = client.post("/medicines", headers=h, json={"medicine_name": "Brand New"}).json()["id"]
    alerts = client.get("/alerts?unread_only=true", headers=h).json()
    assert [(a["alert_type"], a["medicine_id"], a["severity"]) for a in alerts] == [("OUT_OF_STOCK", mid, "CRITICAL")]
    client.post("/alerts/refresh", headers=h)                      # refreshing never duplicates
    assert len(client.get("/alerts", headers=h).json()) == 1


def test_low_expiring_expired_alerts_and_resolution(client, session_factory):
    h = login_as(client, session_factory)
    low = make_medicine(session_factory, "Low One", reorder=15)
    soon = make_medicine(session_factory, "Soon One", reorder=1)
    old = make_medicine(session_factory, "Old One", reorder=1)
    add_batch(session_factory, low, 10, 365)
    add_batch(session_factory, soon, 50, 45)
    add_batch(session_factory, old, 5, -2)
    client.post("/alerts/refresh", headers=h)
    kinds = {(a["alert_type"], a["medicine_id"]) for a in client.get("/alerts?unread_only=true", headers=h).json()}
    assert ("LOW_STOCK", low) in kinds and ("EXPIRING_SOON", soon) in kinds
    assert ("EXPIRED", old) in kinds and ("OUT_OF_STOCK", old) in kinds       # expired stock is not usable
    add_batch(session_factory, low, 100, 365, number="RESTOCK")
    client.post("/alerts/refresh", headers=h)
    kinds = {(a["alert_type"], a["medicine_id"]) for a in client.get("/alerts?unread_only=true", headers=h).json()}
    assert ("LOW_STOCK", low) not in kinds                                    # resolved
    one = client.get("/alerts?unread_only=true", headers=h).json()[0]["id"]
    assert client.put(f"/alerts/{one}/read", headers=h).json()["is_read"] is True


def test_reports(client, session_factory):
    h = login_as(client, session_factory)
    mid = make_medicine(session_factory, "Dolo 500")
    add_batch(session_factory, mid, 20, 30, price="2.00")
    add_batch(session_factory, mid, 7, -1, price="2.00")
    d = client.get("/reports/dashboard", headers=h).json()
    assert d["total_units"] == 20 and d["expiring_soon_batches"] == 1 and d["out_of_stock_count"] == 0
    assert d["todays_sales"] == "0.00"                              # money is a string, never a float
    inv = client.get("/reports/inventory", headers=h).json()
    assert inv["medicines"][0]["stock_value"] == "40.00" and inv["medicines"][0]["expired_or_unusable_units"] == 7
    assert client.get("/reports/sales?report_date=2020-01-01", headers=h).json()["transactions"] == 0
    assert client.get("/reports/prescriptions", headers=h).json() == {"total": 0, "by_status": {}}
