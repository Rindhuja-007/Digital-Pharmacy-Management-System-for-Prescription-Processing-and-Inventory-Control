from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_staff
from ..errors import AppError
from ..models import Prescription, User
from ..schemas import (ItemIn, PrescriptionItemOut, PrescriptionListOut, PrescriptionOut, VerifyIn)
from ..services import prescriptions as svc
from ..utils import money_json

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])


def _detail(rx: Prescription) -> PrescriptionOut:
    out = PrescriptionOut.model_validate(rx)
    out.item_count = len(rx.items)
    out.has_processed_image = bool(rx.processed_image_path)
    return out


@router.get("", response_model=list[PrescriptionListOut])
def list_prescriptions(status: str | None = None, limit: int = Query(100, ge=1, le=500),
                       offset: int = Query(0, ge=0), _: User = Depends(require_staff),
                       db: Session = Depends(get_db)):
    return svc.list_prescriptions(db, status, limit, offset)


@router.post("/upload", response_model=PrescriptionOut, status_code=201)
async def upload(file: UploadFile = File(...), patient_reference: str | None = Form(None),
                 doctor_name: str | None = Form(None), user: User = Depends(require_staff),
                 db: Session = Depends(get_db)):
    data = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    rx = svc.create_prescription(db, user, data, file.content_type, file.filename, patient_reference, doctor_name)
    return _detail(svc.get_prescription(db, rx.id))


@router.get("/{rx_id}", response_model=PrescriptionOut)
def get_one(rx_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    return _detail(svc.get_prescription(db, rx_id))


@router.get("/{rx_id}/image")
def get_image(rx_id: int, kind: str = Query("original", pattern="^(original|processed)$"),
              _: User = Depends(require_staff), db: Session = Depends(get_db)):
    rx = svc.get_prescription(db, rx_id, with_items=False)
    rel = rx.processed_image_path if kind == "processed" else rx.image_path
    if not rel:
        raise AppError(404, "Processed image not available yet")
    path = svc.abs_path(rel)
    if not path.exists():
        raise AppError(404, "Image file is missing on the server")
    return FileResponse(path)


@router.post("/{rx_id}/preprocess", response_model=PrescriptionOut)
def preprocess(rx_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    svc.run_preprocess(db, rx_id)
    return _detail(svc.get_prescription(db, rx_id))


@router.post("/{rx_id}/process", response_model=PrescriptionOut)
def process(rx_id: int, source: str = Query("auto", pattern="^(auto|original|processed)$"),
            _: User = Depends(require_staff), db: Session = Depends(get_db)):
    svc.run_ocr_stage(db, rx_id, source)
    return _detail(svc.get_prescription(db, rx_id))


@router.post("/{rx_id}/extract")
def extract(rx_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    rx, skipped = svc.run_extract(db, rx_id)
    return {"prescription": _detail(svc.get_prescription(db, rx_id)).model_dump(mode="json"),
            "skipped_lines": skipped}


@router.post("/{rx_id}/match")
def match(rx_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    return {"prescription_id": rx_id, "matches": svc.run_match(db, rx_id)}


@router.post("/{rx_id}/items", response_model=PrescriptionItemOut, status_code=201)
def add_item(rx_id: int, body: ItemIn, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    return svc.add_item(db, rx_id, body)


@router.put("/{rx_id}/verify", response_model=PrescriptionOut)
def verify(rx_id: int, body: VerifyIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    svc.verify(db, rx_id, user, body.decisions)
    return _detail(svc.get_prescription(db, rx_id))


@router.post("/{rx_id}/availability")
def availability(rx_id: int, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    return money_json(svc.availability(db, rx_id))
