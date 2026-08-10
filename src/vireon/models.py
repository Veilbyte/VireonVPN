from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .domain import PlanCode


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Normalize DB datetimes; SQLite can return timezone-naive values in development."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def uuid_str() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class SubscriptionKind(StrEnum):
    TRIAL = "trial"
    PAID = "paid"
    REFERRAL = "referral"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_USER = "waiting_user"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class StaffRole(StrEnum):
    MODERATOR = "moderator"
    ADMINISTRATOR = "administrator"
    DEVELOPER = "developer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    referral_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    referrer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    token: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    plan_code: Mapped[PlanCode] = mapped_column(Enum(PlanCode, native_enum=False))
    kind: Mapped[SubscriptionKind] = mapped_column(Enum(SubscriptionKind, native_enum=False))
    device_limit: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_code: Mapped[PlanCode] = mapped_column(Enum(PlanCode, native_enum=False))
    days: Mapped[int] = mapped_column(Integer)
    amount_kopecks: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32), default="mock")
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False), default=PaymentStatus.PENDING
    )
    referral_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReferralReward(Base):
    __tablename__ = "referral_rewards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    referrer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    referred_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    days: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(160))
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, native_enum=False), default=TicketStatus.OPEN
    )
    assigned_staff_id: Mapped[str | None] = mapped_column(
        ForeignKey("staff_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    author_type: Mapped[str] = mapped_column(String(16))
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_staff_id: Mapped[str | None] = mapped_column(
        ForeignKey("staff_users.id"), nullable=True
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StaffUser(Base):
    __tablename__ = "staff_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[StaffRole] = mapped_column(Enum(StaffRole, native_enum=False))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    staff_user_id: Mapped[str | None] = mapped_column(ForeignKey("staff_users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VpnNode(Base):
    __tablename__ = "vpn_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    country_code: Mapped[str] = mapped_column(String(2), index=True)
    config_uri: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
