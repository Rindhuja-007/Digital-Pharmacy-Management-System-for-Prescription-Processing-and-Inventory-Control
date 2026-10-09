import os
import tempfile

# Must be set before the app is imported.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-not-for-production"
os.environ["ADMIN_APPROVAL_CODE"] = "TEST-APPROVAL-CODE"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="pharmacare-test-uploads-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base, get_db, make_engine  # noqa: E402
from app import models  # noqa: E402,F401
from app.main import app  # noqa: E402


@pytest.fixture()
def session_factory():
    engine = make_engine("sqlite://")  # fresh in-memory DB per test
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)


@pytest.fixture()
def client(session_factory):
    def override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def ocr_stub(monkeypatch):
    """Replace real PaddleOCR so tests need no models. Set `ocr_stub.text` / `.confidence`."""
    from app.services import ocr

    class Stub:
        text = "Tab Dolo 500 mg 1-0-1 x 5 days"
        confidence = 93.5

    stub = Stub()
    monkeypatch.setattr(ocr, "run_ocr", lambda path: (stub.text, stub.confidence))
    return stub
