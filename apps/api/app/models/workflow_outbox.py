from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowOutboxEvent(Base):
    __tablename__ = "workflow_outbox_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_workflow_outbox_events_org_id"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_outbox_events_org_idempotency"),
        CheckConstraint("status IN ('pending','processing','published','failed')", name="ck_workflow_outbox_events_status"),
        CheckConstraint("attempt_count >= 0", name="ck_workflow_outbox_events_attempt_count"),
        CheckConstraint("max_attempts >= 1", name="ck_workflow_outbox_events_max_attempts"),
        ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"),
        Index("ix_workflow_outbox_events_status_schedule_lease", "status", "next_attempt_at", "lease_expires_at"),
        Index("ix_workflow_outbox_events_org_conversation_time", "organization_id", "conversation_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="8")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class WorkflowEventConsumption(Base):
    __tablename__ = "workflow_event_consumptions"
    __table_args__ = (
        UniqueConstraint("organization_id", "event_id", "consumer_name", name="uq_workflow_event_consumptions_org_event_consumer"),
        ForeignKeyConstraint(["organization_id", "event_id"], ["workflow_outbox_events.organization_id", "workflow_outbox_events.id"], ondelete="CASCADE"),
        Index("ix_workflow_event_consumptions_org_consumer_time", "organization_id", "consumer_name", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    consumer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
