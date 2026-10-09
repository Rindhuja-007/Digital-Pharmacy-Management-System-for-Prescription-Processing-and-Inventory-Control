"""Settings read from environment variables (never hard-coded secrets)."""
import logging
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
log = logging.getLogger("pharmacare")

_generated_secret: str | None = None


class Settings:
    @property
    def DATABASE_URL(self) -> str:
        return os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'pharmacare.db'}")

    @property
    def JWT_SECRET(self) -> str:
        global _generated_secret
        value = os.getenv("JWT_SECRET")
        if value:
            return value
        if _generated_secret is None:
            _generated_secret = secrets.token_urlsafe(48)
            log.warning("JWT_SECRET is not set; using a random per-process secret "
                        "(all tokens become invalid on restart). Set JWT_SECRET in production.")
        return _generated_secret

    JWT_ALGORITHM = "HS256"
    JWT_EXPIRE_HOURS = 8

    @property
    def ADMIN_APPROVAL_CODE(self) -> str:
        return os.getenv("ADMIN_APPROVAL_CODE", "")

    @property
    def CORS_ORIGINS(self) -> list[str]:
        raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def UPLOAD_DIR(self) -> Path:
        return Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads"))).resolve()

    MAX_UPLOAD_BYTES = 10 * 1024 * 1024
    EXPIRY_WARNING_DAYS = 90


settings = Settings()
