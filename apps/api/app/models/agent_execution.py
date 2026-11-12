from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_agent_executions_org_id"),
        UniqueConstraint(
            "organization_id",
            "agent_profile_id",
            "idempotency_key",
            name="uq_agent_executions_org_agent_idempotency",
        ),
        CheckConstraint(
            "status IN ('queued','running','waiting_approval','succeeded','failed','cancelled')",
            name="ck_agent_executions_status",
        ),
        CheckConstraint("retry_count >= 0", name="ck_agent_executions_retry_count"),
        CheckConstraint("max_retries >= 0", name="ck_agent_executions_max_retries"),
        CheckConstraint("timeout_seconds >= 1", name="ck_agent_executions_timeout_seconds"),
        CheckConstraint("token_input_count >= 0", name="ck_agent_executions_token_input_count"),
        CheckConstraint("token_output_count >= 0", name="ck_agent_executions_token_output_count"),
        CheckConstraint("duration_ms >= 0", name="ck_agent_executions_duration_ms"),
        ForeignKeyConstraint(
            ["organization_id", "agent_profile_id"],
            ["agent_profiles.organization_id", "agent_profiles.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "agent_version_id"],
            ["agent_versions.organization_id", "agent_versions.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_version_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requested_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="queued", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="900")
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_input_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    token_output_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
