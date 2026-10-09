"""SQLAlchemy 2.0 models (10 tables). Money columns are Numeric -> Decimal."""
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
                        Numeric, String, Text, TypeDecorator)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(StrEnum):
    ADMIN = "ADMIN"
    PHARMACIST = "PHARMACIST"


class RxStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSED = "PROCESSED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    DISPENSED = "DISPENSED"


class ItemStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AlertType(StrEnum):
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


Money = Numeric(12, 2)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=Role.PHARMACIST.value)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    contact: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Medicine(Base):
    __tablename__ = "medicines"
    id: Mapped[int] = mapped_column(primary_key=True)
    barcode: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    medicine_name: Mapped[str] = mapped_column(String(200), index=True)
    generic_name: Mapped[str | None] = mapped_column(String(200))
    composition: Mapped[str | None] = mapped_column(Text)
    brand_name: Mapped[str | None] = mapped_column(String(200))
    strength: Mapped[str | None] = mapped_column(String(60))
    dosage_form: Mapped[str | None] = mapped_column(String(60))
    unit_of_measure: Mapped[str | None] = mapped_column(String(30))
    pack_size: Mapped[str | None] = mapped_column(String(60))
    category: Mapped[str | None] = mapped_column(String(100))
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    prescription_required: Mapped[bool] = mapped_column(Boolean, default=False)
    rack_location: Mapped[str | None] = mapped_column(String(60))
    shelf_number: Mapped[str | None] = mapped_column(String(60))
    storage_condition: Mapped[str | None] = mapped_column(String(120))
    reorder_level: Mapped[int] = mapped_column(Integer, default=15)
    mrp: Mapped[Decimal | None] = mapped_column(Money)
    hsn_code: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    batches: Mapped[list["Batch"]] = relationship(back_populates="medicine")


class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (
        Index("ix_batches_medicine_expiry", "medicine_id", "expiry_date"),
        CheckConstraint("quantity >= 0", name="ck_batch_qty_nonneg"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"))
    batch_number: Mapped[str] = mapped_column(String(60))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    expiry_date: Mapped[date] = mapped_column(Date)
    purchase_price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    selling_price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    received_date: Mapped[date] = mapped_column(Date, default=date.today)
    reorder_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)

    medicine: Mapped[Medicine] = relationship(back_populates="batches")
    supplier: Mapped[Supplier | None] = relationship()


class Prescription(Base):
    __tablename__ = "prescriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    patient_reference: Mapped[str | None] = mapped_column(String(120))
    doctor_name: Mapped[str | None] = mapped_column(String(120))
    image_path: Mapped[str] = mapped_column(String(300))
    processed_image_path: Mapped[str | None] = mapped_column(String(300))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=RxStatus.UPLOADED.value, index=True)
    confidence_score: Mapped[float | None] = mapped_column()
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    items: Mapped[list["PrescriptionItem"]] = relationship(
        back_populates="prescription", cascade="all, delete-orphan", order_by="PrescriptionItem.id")


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescriptions.id", ondelete="CASCADE"))
    medicine_id: Mapped[int | None] = mapped_column(ForeignKey("medicines.id"), nullable=True)
    extracted_medicine_name: Mapped[str] = mapped_column(String(200))
    matched_medicine_name: Mapped[str | None] = mapped_column(String(200))
    dosage: Mapped[str | None] = mapped_column(String(80))
    frequency: Mapped[str | None] = mapped_column(String(80))
    duration: Mapped[str | None] = mapped_column(String(80))
    quantity: Mapped[int | None] = mapped_column(Integer)
    confidence_score: Mapped[float | None] = mapped_column()
    verification_status: Mapped[str] = mapped_column(String(20), default=ItemStatus.PENDING.value)

    prescription: Mapped[Prescription] = relationship(back_populates="items")
    medicine: Mapped[Medicine | None] = relationship()


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int | None] = mapped_column(ForeignKey("prescriptions.id"), nullable=True)
    pharmacist_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    subtotal: Mapped[Decimal] = mapped_column(Money)
    discount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    tax: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total_amount: Mapped[Decimal] = mapped_column(Money)
    transaction_type: Mapped[str] = mapped_column(String(20), default="SALE")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    prescription: Mapped[Prescription | None] = relationship()
    pharmacist: Mapped[User] = relationship()
    items: Mapped[list["TransactionItem"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", order_by="TransactionItem.id")


class TransactionItem(Base):
    __tablename__ = "transaction_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    total_price: Mapped[Decimal] = mapped_column(Money)

    transaction: Mapped[Transaction] = relationship(back_populates="items")
    medicine: Mapped[Medicine] = relationship()
    batch: Mapped[Batch] = relationship()


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(20), index=True)
    medicine_id: Mapped[int | None] = mapped_column(ForeignKey("medicines.id"), nullable=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"), nullable=True)
    message: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(20), default=Severity.INFO.value)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
