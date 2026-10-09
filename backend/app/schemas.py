"""Pydantic request/response models. Money is always Decimal (serialised as a string)."""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
Username = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True,
                                            min_length=3, max_length=60, pattern=r"^[a-z0-9_.\-]+$")]
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=EMAIL_RE, max_length=200)]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class UserOut(ORM):
    id: int
    name: str
    username: str
    email: str
    role: str
    is_active: bool
    is_approved: bool
    approved_by: int | None = None
    created_at: datetime


class RegisterAdminIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    username: Username
    email: Email
    password: Password
    approval_code: str | None = None


class StaffCreateIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    username: Username
    email: Email
    password: Password
    role: Literal["ADMIN", "PHARMACIST"] = "PHARMACIST"


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- medicines ----------
class MedicineBase(BaseModel):
    barcode: str | None = Field(default=None, max_length=64)
    generic_name: str | None = None
    composition: str | None = None
    brand_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None
    unit_of_measure: str | None = None
    pack_size: str | None = None
    category: str | None = None
    manufacturer: str | None = None
    prescription_required: bool = False
    rack_location: str | None = None
    shelf_number: str | None = None
    storage_condition: str | None = None
    reorder_level: int = Field(default=15, ge=0)
    mrp: Money | None = None
    hsn_code: str | None = None
    description: str | None = None


class MedicineIn(MedicineBase):
    medicine_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class MedicineUpdate(BaseModel):
    barcode: str | None = None
    medicine_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    generic_name: str | None = None
    composition: str | None = None
    brand_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None
    unit_of_measure: str | None = None
    pack_size: str | None = None
    category: str | None = None
    manufacturer: str | None = None
    prescription_required: bool | None = None
    rack_location: str | None = None
    shelf_number: str | None = None
    storage_condition: str | None = None
    reorder_level: int | None = Field(default=None, ge=0)
    mrp: Money | None = None
    hsn_code: str | None = None
    description: str | None = None


class MedicineOut(MedicineBase, ORM):
    id: int
    medicine_name: str
    created_at: datetime
    updated_at: datetime


# ---------- inventory ----------
class StockIn(BaseModel):
    medicine_id: int
    batch_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    quantity: int = Field(gt=0)
    expiry_date: date
    purchase_price: Money = Decimal("0")
    selling_price: Money
    supplier_id: int | None = None
    received_date: date | None = None
    reorder_level: int | None = Field(default=None, ge=0)
    barcode: str | None = None


class BatchUpdate(BaseModel):
    batch_number: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    expiry_date: date | None = None
    purchase_price: Money | None = None
    selling_price: Money | None = None
    supplier_id: int | None = None
    reorder_level: int | None = Field(default=None, ge=0)
    barcode: str | None = None


class BatchOut(ORM):
    id: int
    medicine_id: int
    medicine_name: str | None = None
    batch_number: str
    quantity: int
    expiry_date: date
    purchase_price: Decimal
    selling_price: Decimal
    supplier_id: int | None = None
    received_date: date
    reorder_level: int | None = None
    barcode: str | None = None
    is_expired: bool = False
    is_usable: bool = False


class SupplierIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    contact: str | None = None
    email: str | None = None
    address: str | None = None


class SupplierOut(SupplierIn, ORM):
    id: int
    created_at: datetime


class AlertOut(ORM):
    id: int
    alert_type: str
    medicine_id: int | None
    batch_id: int | None
    message: str
    severity: str
    is_read: bool
    created_at: datetime


# ---------- dispensing ----------
class DispenseIn(BaseModel):
    prescription_id: int
    confirmed_dispensing: bool = False
    discount: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] = Decimal("0")
    tax: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] = Decimal("0")


class ReceiptItemOut(BaseModel):
    medicine_id: int
    medicine_name: str
    batch_id: int
    batch_number: str
    expiry_date: date
    quantity: int
    unit_price: Decimal
    total_price: Decimal


class ReceiptOut(BaseModel):
    id: int
    prescription_id: int | None
    prescription_number: str | None
    patient_reference: str | None
    pharmacist_id: int
    pharmacist_username: str
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    total_amount: Decimal
    transaction_type: str
    created_at: datetime
    items: list[ReceiptItemOut]


# ---------- prescriptions ----------
class PrescriptionItemOut(ORM):
    id: int
    prescription_id: int
    medicine_id: int | None
    extracted_medicine_name: str
    matched_medicine_name: str | None
    dosage: str | None
    frequency: str | None
    duration: str | None
    quantity: int | None
    confidence_score: float | None
    verification_status: str


class PrescriptionListOut(ORM):
    id: int
    prescription_number: str
    patient_reference: str | None
    doctor_name: str | None
    status: str
    confidence_score: float | None
    created_by: int
    verified_by: int | None
    verified_at: datetime | None
    created_at: datetime
    item_count: int = 0


class PrescriptionOut(PrescriptionListOut):
    extracted_text: str | None
    has_processed_image: bool = False
    items: list[PrescriptionItemOut] = []


class ItemIn(BaseModel):
    extracted_medicine_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    medicine_id: int | None = None
    dosage: str | None = Field(default=None, max_length=80)
    frequency: str | None = Field(default=None, max_length=80)
    duration: str | None = Field(default=None, max_length=80)
    quantity: int | None = Field(default=None, gt=0)


class VerifyDecision(BaseModel):
    item_id: int
    decision: Literal["VERIFIED", "REJECTED"]
    medicine_id: int | None = None
    quantity: int | None = None
    dosage: str | None = Field(default=None, max_length=80)
    frequency: str | None = Field(default=None, max_length=80)
    duration: str | None = Field(default=None, max_length=80)


class VerifyIn(BaseModel):
    decisions: list[VerifyDecision] = Field(min_length=1)
