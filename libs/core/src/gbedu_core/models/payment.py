from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gbedu_core._uuid7 import uuid7str
from gbedu_core.db import Base, TimestampMixin

if TYPE_CHECKING:
	from gbedu_core.models.user import User


class PaymentProvider(str, enum.Enum):
	stripe = "stripe"
	paystack = "paystack"


class WebhookEvent(Base):
	"""Durable deduplication record for processed payment webhooks.

	Redis idempotency keys are cleared on restart; this table survives.
	Created immediately before processing begins; presence means the event
	has been (or is being) processed. Used by both Stripe and Paystack handlers.
	"""

	__tablename__ = "webhook_events"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	# unique=True creates a unique constraint; PostgreSQL implicitly creates a
	# unique index for it — no separate Index() needed.
	event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
	provider: Mapped[str] = mapped_column(
		Enum(PaymentProvider, name="payment_provider", create_type=False),
		nullable=False,
	)
	event_type: Mapped[str] = mapped_column(String(128), nullable=False)
	processed_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False,
	)
	metadata_: Mapped[dict[str, Any]] = mapped_column(
		"metadata", JSONB, nullable=False, default=dict,
	)


class PaymentStatus(str, enum.Enum):
	pending = "pending"
	succeeded = "succeeded"
	failed = "failed"
	refunded = "refunded"
	partially_refunded = "partially_refunded"
	disputed = "disputed"


class InvoiceStatus(str, enum.Enum):
	draft = "draft"
	open = "open"
	paid = "paid"
	void = "void"
	uncollectible = "uncollectible"


class SubscriptionInterval(str, enum.Enum):
	month = "month"
	year = "year"


class Subscription(Base, TimestampMixin):
	__tablename__ = "subscriptions"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	user_id: Mapped[str] = mapped_column(
		String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
	)

	provider: Mapped[PaymentProvider] = mapped_column(
		Enum(PaymentProvider, name="payment_provider"), nullable=False
	)
	# Provider-native subscription ID — e.g. sub_xxx (Stripe) or SUB_xxx (Paystack)
	provider_subscription_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
	provider_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)

	tier: Mapped[str] = mapped_column(String(32), nullable=False)
	interval: Mapped[SubscriptionInterval] = mapped_column(
		Enum(SubscriptionInterval, name="subscription_interval"), nullable=False
	)

	status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

	# Amounts in minor currency units (cents / kobo)
	amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
	currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

	current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
	current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
	cancel_at_period_end: Mapped[bool] = mapped_column(nullable=False, default=False)
	cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
	trial_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
	trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

	metadata_: Mapped[dict[str, Any]] = mapped_column(
		"metadata", JSONB, nullable=False, default=dict, server_default="{}"
	)

	user: Mapped[User] = relationship("User", back_populates="subscriptions", lazy="noload")
	payments: Mapped[list[Payment]] = relationship("Payment", back_populates="subscription", lazy="noload")

	__table_args__ = (Index("ix_subscriptions_user_status", "user_id", "status"),)

	def __repr__(self) -> str:
		return (
			f"<Subscription id={self.id!r} tier={self.tier!r} "
			f"provider={self.provider.value!r} status={self.status!r}>"
		)


class Payment(Base, TimestampMixin):
	__tablename__ = "payments"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	user_id: Mapped[str] = mapped_column(
		String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
	)
	subscription_id: Mapped[str | None] = mapped_column(
		String(36), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True, index=True
	)

	provider: Mapped[PaymentProvider] = mapped_column(
		Enum(PaymentProvider, name="payment_provider"), nullable=False
	)
	provider_payment_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
	provider_charge_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

	status: Mapped[PaymentStatus] = mapped_column(
		Enum(PaymentStatus, name="payment_status"), nullable=False, index=True
	)

	amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
	currency: Mapped[str] = mapped_column(String(3), nullable=False)
	refunded_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

	description: Mapped[str | None] = mapped_column(Text, nullable=True)
	failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
	failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)

	paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

	metadata_: Mapped[dict[str, Any]] = mapped_column(
		"metadata", JSONB, nullable=False, default=dict, server_default="{}"
	)

	user: Mapped[User] = relationship("User", back_populates="payments", lazy="noload")
	subscription: Mapped[Subscription | None] = relationship(
		"Subscription", back_populates="payments", lazy="noload"
	)

	@property
	def amount_decimal(self) -> float:
		return self.amount_minor / 100

	def __repr__(self) -> str:
		return (
			f"<Payment id={self.id!r} amount={self.amount_minor} {self.currency} "
			f"status={self.status.value!r}>"
		)


class Invoice(Base, TimestampMixin):
	__tablename__ = "invoices"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	user_id: Mapped[str] = mapped_column(
		String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
	)
	subscription_id: Mapped[str | None] = mapped_column(
		String(36), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
	)
	payment_id: Mapped[str | None] = mapped_column(
		String(36), ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
	)

	provider: Mapped[PaymentProvider] = mapped_column(
		Enum(PaymentProvider, name="payment_provider"), nullable=False
	)
	provider_invoice_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

	status: Mapped[InvoiceStatus] = mapped_column(
		Enum(InvoiceStatus, name="invoice_status"), nullable=False, index=True
	)

	subtotal_minor: Mapped[int] = mapped_column(Integer, nullable=False)
	tax_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
	total_minor: Mapped[int] = mapped_column(Integer, nullable=False)
	currency: Mapped[str] = mapped_column(String(3), nullable=False)

	invoice_pdf_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
	due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
	paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

	line_items: Mapped[list[dict[str, Any]]] = mapped_column(
		JSONB, nullable=False, default=list, server_default="[]"
	)

	def __repr__(self) -> str:
		return (
			f"<Invoice id={self.id!r} total={self.total_minor} {self.currency} "
			f"status={self.status.value!r}>"
		)
