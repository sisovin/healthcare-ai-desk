from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentExecutionTask(Base):
    __tablename__ = "agent_execution_tasks"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_agent_execution_tasks_org_id"),
        UniqueConstraint(
            "organization_id",
            "execution_id",
            "queue_position",
            name="uq_agent_execution_tasks_org_execution_position",
        ),
        CheckConstraint("queue_position >= 1", name="ck_agent_execution_tasks_queue_position"),
        CheckConstraint(
            "status IN ('pending','blocked','running','waiting_approval','succeeded','failed','cancelled')",
            name="ck_agent_execution_tasks_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_agent_execution_tasks_attempt_count"),
        CheckConstraint("max_attempts >= 1", name="ck_agent_execution_tasks_max_attempts"),
        ForeignKeyConstraint(
            ["organization_id", "execution_id"],
            ["agent_executions.organization_id", "agent_executions.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    queue_position: Mapped[int] = mapped_column(Integer, nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    depends_on_task_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agent_execution_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
