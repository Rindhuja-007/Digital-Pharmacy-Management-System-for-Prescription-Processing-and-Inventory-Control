from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    kwargs = {}
    sqlite = url.startswith("sqlite")
    if sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:") or ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if sqlite:
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # enforce foreign keys on SQLite
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


engine = make_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()  # closing an uncommitted session rolls it back


def init_db():
    from . import models  # noqa: F401  (register tables)
    Base.metadata.create_all(bind=engine)
