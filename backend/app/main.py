import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import init_db
from .errors import AppError
from .routers import alerts, auth, inventory, medicines, reports, suppliers, transactions, prescriptions
from .services.ocr import _get_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if settings.OCR_WARMUP:
        try:
            _get_engine()
        except AppError:
            logging.getLogger("pharmacare").exception("OCR warmup failed; OCR requests will return an error")
    yield


app = FastAPI(title="PharmaCare API", version="1.0.0",
              description="Pharmacist-assisted digital pharmacy. The software suggests; a human confirms.",
              lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                        headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    """Same 422 status, plus a human-readable `message` the UI can show directly."""
    from fastapi.encoders import jsonable_encoder
    errors = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
    parts = []
    for e in errors:
        loc = ".".join(str(x) for x in e.get("loc", []) if x not in ("body", "query", "path"))
        parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
    return JSONResponse(status_code=422, content={"detail": errors, "message": "; ".join(parts)})


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


for r in (auth, medicines, inventory, alerts, reports, suppliers, transactions, prescriptions):
    app.include_router(r.router)
