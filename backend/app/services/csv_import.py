"""Medicine CSV import: creates medicines, sets rack locations, appends batches."""
import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import AppError
from ..models import Batch, Medicine, Supplier
from .audit import log_action

MAX_ROWS = 5000
SAMPLE_CSV = (
    "medicine_name,generic_name,composition,brand_name,strength,dosage_form,unit_of_measure,pack_size,"
    "category,manufacturer,prescription_required,rack_location,shelf_number,storage_condition,"
    "reorder_level,mrp,hsn_code,barcode,batch_number,quantity,expiry_date,purchase_price,selling_price,supplier\n"
    "Dolo 650,Paracetamol,Paracetamol 650 mg,Dolo,650 mg,Tablet,tablet,15 tablets,Analgesic,Micro Labs,false,"
    "A1,2,Store below 30C,20,30.00,30049099,8901234500011,DL650-01,200,2027-06-30,1.10,1.80,MedSupply Co\n"
    "Amoxicillin 500,Amoxicillin,Amoxicillin 500 mg,Mox,500 mg,Capsule,capsule,10 capsules,Antibiotic,"
    "Cipla,true,B2,1,Store below 25C,15,60.00,30041010,,AMX500-07,90,2027-01-31,3.00,4.50,MedSupply Co\n"
    "Metformin 500,Metformin Hydrochloride,Metformin Hydrochloride 500 mg,Glycomet,500 mg,Tablet,tablet,"
    "20 tablets,Antidiabetic,USV,true,C3,4,,15,22.00,30049099,,,,,,,\n"
)


def _s(v):
    v = (v or "").strip()
    return v or None


def _dec(v, field):
    try:
        d = Decimal(v.strip())
    except (InvalidOperation, AttributeError):
        raise ValueError(f"{field} must be a number")
    if d < 0:
        raise ValueError(f"{field} cannot be negative")
    return d.quantize(Decimal("0.01"))


def _int(v, field, minimum=0):
    try:
        n = int(v.strip())
    except (ValueError, AttributeError):
        raise ValueError(f"{field} must be a whole number")
    if n < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return n


def _bool(v):
    return (v or "").strip().lower() in ("1", "true", "yes", "y")


def import_medicines_csv(db: Session, raw: bytes, user_id: int) -> dict:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError(422, "CSV must be UTF-8 encoded")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "medicine_name" not in [f.strip() for f in reader.fieldnames]:
        raise AppError(422, "CSV must have a header row including 'medicine_name'")
    result = {"created_medicines": 0, "updated_medicines": 0, "batches_added": 0,
              "skipped_batches": 0, "errors": []}
    for n, row in enumerate(reader, start=2):
        if n - 1 > MAX_ROWS:
            raise AppError(422, f"CSV has more than {MAX_ROWS} rows")
        row = {(k or "").strip(): (v or "") for k, v in row.items()}
        if not any(v.strip() for v in row.values()):
            continue
        try:
            with db.begin_nested():  # a bad row never affects the others
                _import_row(db, row, result)
        except ValueError as e:
            result["errors"].append({"row": n, "message": str(e)})
    log_action(db, user_id, "IMPORT_MEDICINES_CSV", "medicine", None,
               f"CSV import: {result['created_medicines']} created, {result['updated_medicines']} updated, "
               f"{result['batches_added']} batches added, {len(result['errors'])} row errors")
    return result


def _import_row(db: Session, row: dict, result: dict):
    name = _s(row.get("medicine_name"))
    if not name:
        raise ValueError("medicine_name is required")
    barcode = _s(row.get("barcode"))
    strength = _s(row.get("strength"))
    med = None
    if barcode:
        med = db.scalar(select(Medicine).where(Medicine.barcode == barcode))
    if med is None:
        q = select(Medicine).where(func.lower(Medicine.medicine_name) == name.lower())
        q = q.where(func.lower(func.coalesce(Medicine.strength, "")) == (strength or "").lower())
        med = db.scalar(q)

    # validate everything before writing anything
    fields = {k: _s(row.get(k)) for k in (
        "generic_name", "composition", "brand_name", "dosage_form", "unit_of_measure", "pack_size",
        "category", "manufacturer", "rack_location", "shelf_number", "storage_condition", "hsn_code",
        "description")}
    reorder = _int(row["reorder_level"], "reorder_level") if _s(row.get("reorder_level")) else None
    mrp = _dec(row["mrp"], "mrp") if _s(row.get("mrp")) else None
    batch_no, qty_raw = _s(row.get("batch_number")), _s(row.get("quantity"))
    batch = None
    if batch_no or qty_raw:
        if not (batch_no and qty_raw):
            raise ValueError("batch_number and quantity must be given together")
        try:
            exp = date.fromisoformat((row.get("expiry_date") or "").strip())
        except ValueError:
            raise ValueError("expiry_date must be YYYY-MM-DD")
        batch = dict(batch_number=batch_no, quantity=_int(qty_raw, "quantity", 1), expiry_date=exp,
                     purchase_price=_dec(row.get("purchase_price") or "0", "purchase_price"),
                     selling_price=_dec(row.get("selling_price") or "", "selling_price"))
    if med is None:
        med = Medicine(medicine_name=name, strength=strength, barcode=barcode,
                       prescription_required=_bool(row.get("prescription_required")),
                       reorder_level=reorder if reorder is not None else 15, mrp=mrp, **fields)
        db.add(med)
        db.flush()
        result["created_medicines"] += 1
    else:
        changed = False
        for k in ("rack_location", "shelf_number"):  # existing medicines only get location updates
            if fields[k] and getattr(med, k) != fields[k]:
                setattr(med, k, fields[k])
                changed = True
        if changed:
            result["updated_medicines"] += 1
    if batch:
        dup = db.scalar(select(Batch).where(Batch.medicine_id == med.id,
                                            Batch.batch_number == batch["batch_number"]))
        if dup:
            result["skipped_batches"] += 1
            return
        supplier_id = None
        sname = _s(row.get("supplier"))
        if sname:
            sup = db.scalar(select(Supplier).where(func.lower(Supplier.name) == sname.lower()))
            if not sup:
                sup = Supplier(name=sname)
                db.add(sup)
                db.flush()
            supplier_id = sup.id
        db.add(Batch(medicine_id=med.id, supplier_id=supplier_id, **batch))
        result["batches_added"] += 1
