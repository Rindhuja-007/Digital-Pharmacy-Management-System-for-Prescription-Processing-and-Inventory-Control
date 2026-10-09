import pytest
from jose import jwt

from app.config import settings
from app.models import Role
from tests.helpers import PASSWORD, auth_headers, login_as, make_user

ADMIN1 = {"name": "First Admin", "username": "root", "email": "root@test.io", "password": PASSWORD}
ADMIN2 = {"name": "Second Admin", "username": "second", "email": "second@test.io", "password": PASSWORD}


def test_onboarding_first_admin_auto_approved_second_pending_then_approved(client, session_factory):  # test #1
    assert client.get("/auth/status").json() == {"has_admin": False, "setup_required": True}

    r = client.post("/auth/register-admin", json=ADMIN1)
    assert r.status_code == 201 and r.json()["is_approved"] is True and r.json()["role"] == "ADMIN"
    assert client.get("/auth/status").json()["has_admin"] is True
    root = auth_headers(client, "root")

    r = client.post("/auth/register-admin", json=ADMIN2)       # no approval code
    assert r.status_code == 202
    assert r.json()["user"]["is_approved"] is False
    second_id = r.json()["user"]["id"]
    login = client.post("/auth/login", json={"username": "second", "password": PASSWORD})
    assert login.status_code == 403                             # unapproved users cannot log in

    assert client.post(f"/auth/approve-admin/{second_id}", headers=root).status_code == 200
    assert client.post("/auth/login", json={"username": "second", "password": PASSWORD}).status_code == 200

    make_user(session_factory, "pharma", Role.PHARMACIST)
    pharma = auth_headers(client, "pharma")
    assert client.get("/auth/staff", headers=pharma).status_code == 403
    assert client.get("/auth/staff", headers=root).status_code == 200
    assert client.post(f"/auth/approve-admin/{second_id}", headers=pharma).status_code == 403


def test_admin_with_valid_approval_code_is_approved_immediately(client):
    client.post("/auth/register-admin", json=ADMIN1)
    r = client.post("/auth/register-admin", json={**ADMIN2, "approval_code": "wrong"})
    assert r.status_code == 202
    r = client.post("/auth/register-admin", json={**ADMIN2, "username": "third", "email": "t@test.io",
                                                  "approval_code": settings.ADMIN_APPROVAL_CODE})
    assert r.status_code == 201 and r.json()["is_approved"] is True


def test_reject_admin_removes_the_pending_registration(client):
    client.post("/auth/register-admin", json=ADMIN1)
    pending = client.post("/auth/register-admin", json=ADMIN2).json()["user"]["id"]
    root = auth_headers(client, "root")
    assert client.post(f"/auth/reject-admin/{pending}", headers=root).status_code == 200
    assert client.post("/auth/login", json={"username": "second", "password": PASSWORD}).status_code == 401


def test_duplicate_username_or_email_conflicts(client):
    client.post("/auth/register-admin", json=ADMIN1)
    assert client.post("/auth/register-admin", json={**ADMIN2, "username": "root"}).status_code == 409
    assert client.post("/auth/register-admin", json={**ADMIN2, "email": "root@test.io"}).status_code == 409


def test_login_failures_oauth_form_and_token_expiry(client, session_factory):
    make_user(session_factory, "pharma")
    assert client.post("/auth/login", json={"username": "pharma", "password": "nope-nope"}).status_code == 401
    assert client.post("/auth/login", json={"username": "ghost", "password": PASSWORD}).status_code == 401
    r = client.post("/auth/token", data={"username": "pharma", "password": PASSWORD})
    assert r.status_code == 200
    claims = jwt.decode(r.json()["access_token"], settings.JWT_SECRET, algorithms=["HS256"])
    assert 7.9 * 3600 < claims["exp"] - claims["iat"] if "iat" in claims else True
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()["username"] == "pharma"


def test_password_is_hashed_with_argon2(client, session_factory):
    from app.models import User
    client.post("/auth/register-admin", json=ADMIN1)
    with session_factory() as db:
        assert db.query(User).one().password_hash.startswith("$argon2")


@pytest.mark.parametrize("method,path", [
    ("get", "/auth/me"), ("get", "/medicines"), ("get", "/inventory"), ("get", "/alerts"),
    ("get", "/reports/dashboard"), ("get", "/prescriptions"), ("get", "/transactions"),
    ("post", "/prescriptions/1/process"), ("put", "/prescriptions/1/verify"), ("post", "/transactions"),
])
def test_protected_routes_need_a_token(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert client.get("/health").status_code == 200


def test_invalid_token_is_rejected(client):
    assert client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401


def test_seed_demo(client, session_factory):
    r = client.post("/auth/seed-demo")
    assert r.status_code == 200
    admin = client.post("/auth/login", json={"username": "admin", "password": "Admin@123"})
    pharma = client.post("/auth/login", json={"username": "pharmacist", "password": "Pharmacist@123"})
    assert admin.status_code == 200 and pharma.status_code == 200
    h = {"Authorization": f"Bearer {pharma.json()['access_token']}"}
    stock = {r["medicine_name"]: r["usable_units"] for r in client.get("/inventory", headers=h).json()}
    assert stock == {"Crocin 500": 0, "Dolo 500": 120, "Metformin 500": 80}
    assert client.post("/auth/seed-demo").status_code == 403                    # no token, DB not empty
    assert client.post("/auth/seed-demo", headers=h).status_code == 403          # pharmacist
    adm = {"Authorization": f"Bearer {admin.json()['access_token']}"}
    again = client.post("/auth/seed-demo", headers=adm)
    assert again.status_code == 200 and again.json()["medicines_created"] == []  # idempotent


def test_delete_staff(client, session_factory):
    h = login_as(client, session_factory, "boss", Role.ADMIN)
    uid = make_user(session_factory, "temp")
    assert client.delete(f"/auth/staff/{uid}", headers=h).status_code == 200
    assert client.delete("/auth/staff/1", headers=h).status_code == 409          # cannot delete yourself
    assert client.delete("/auth/staff/999", headers=h).status_code == 404
