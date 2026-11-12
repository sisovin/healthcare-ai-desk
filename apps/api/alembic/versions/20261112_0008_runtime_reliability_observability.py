"""harden runtime reliability and observability

Revision ID: 20261112_0008
Revises: 20261112_0007
Create Date: 2026-11-12 12:35:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20261112_0008"
down_revision: Union[str, None] = "20261112_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE agent_executions SET status = 'succeeded' WHERE status = 'completed'")
    op.execute("UPDATE agent_execution_tasks SET status = 'succeeded' WHERE status = 'completed'")

    op.add_column("agent_executions", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column(
        "agent_executions",
        sa.Column("timeout_seconds", sa.Integer(), server_default=sa.text("900"), nullable=False),
    )
    op.add_column(
        "agent_executions",
        sa.Column("max_retries", sa.Integer(), server_default=sa.text("2"), nullable=False),
    )
    op.add_column(
        "agent_executions",
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("agent_executions", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "agent_executions",
        sa.Column("token_input_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "agent_executions",
        sa.Column("token_output_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("agent_executions", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column("agent_executions", sa.Column("last_error_code", sa.String(length=64), nullable=True))
    op.add_column("agent_executions", sa.Column("last_error_message", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_agent_executions_org_agent_idempotency",
        "agent_executions",
        ["organization_id", "agent_profile_id", "idempotency_key"],
    )

    op.add_column("agent_execution_tasks", sa.Column("depends_on_task_id", sa.String(length=36), nullable=True))
    op.add_column("agent_execution_tasks", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "agent_execution_tasks",
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "agent_execution_tasks",
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
    )
    op.add_column("agent_execution_tasks", sa.Column("last_error_code", sa.String(length=64), nullable=True))
    op.add_column("agent_execution_tasks", sa.Column("last_error_message", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_agent_execution_tasks_depends_on_task_id",
        "agent_execution_tasks",
        "agent_execution_tasks",
        ["depends_on_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agent_execution_tasks_depends_on_task_id", "agent_execution_tasks", ["depends_on_task_id"], unique=False)
    op.create_index("ix_agent_execution_tasks_scheduled_at", "agent_execution_tasks", ["scheduled_at"], unique=False)

    op.add_column("agent_execution_approvals", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_execution_approvals", sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_agent_execution_approvals_expires_at", "agent_execution_approvals", ["expires_at"], unique=False)

    op.drop_constraint("ck_agent_executions_status", "agent_executions", type_="check")
    op.create_check_constraint(
        "ck_agent_executions_status",
        "agent_executions",
        "status IN ('queued','running','waiting_approval','succeeded','failed','cancelled')",
    )
    op.create_check_constraint("ck_agent_executions_retry_count", "agent_executions", "retry_count >= 0")
    op.create_check_constraint("ck_agent_executions_max_retries", "agent_executions", "max_retries >= 0")
    op.create_check_constraint("ck_agent_executions_timeout_seconds", "agent_executions", "timeout_seconds >= 1")
    op.create_check_constraint("ck_agent_executions_token_input_count", "agent_executions", "token_input_count >= 0")
    op.create_check_constraint("ck_agent_executions_token_output_count", "agent_executions", "token_output_count >= 0")
    op.create_check_constraint("ck_agent_executions_duration_ms", "agent_executions", "duration_ms IS NULL OR duration_ms >= 0")

    op.drop_constraint("ck_agent_execution_tasks_status", "agent_execution_tasks", type_="check")
    op.create_check_constraint(
        "ck_agent_execution_tasks_status",
        "agent_execution_tasks",
        "status IN ('pending','blocked','running','waiting_approval','succeeded','failed','cancelled')",
    )
    op.create_check_constraint("ck_agent_execution_tasks_attempt_count", "agent_execution_tasks", "attempt_count >= 0")
    op.create_check_constraint("ck_agent_execution_tasks_max_attempts", "agent_execution_tasks", "max_attempts >= 1")

    op.drop_constraint("ck_agent_execution_approvals_status", "agent_execution_approvals", type_="check")
    op.create_check_constraint(
        "ck_agent_execution_approvals_status",
        "agent_execution_approvals",
        "status IN ('pending','approved','rejected','expired')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_execution_approvals_status", "agent_execution_approvals", type_="check")
    op.create_check_constraint(
        "ck_agent_execution_approvals_status",
        "agent_execution_approvals",
        "status IN ('pending','approved','rejected')",
    )
    op.drop_index("ix_agent_execution_approvals_expires_at", table_name="agent_execution_approvals")
    op.drop_column("agent_execution_approvals", "expired_at")
    op.drop_column("agent_execution_approvals", "expires_at")

    op.drop_constraint("ck_agent_execution_tasks_max_attempts", "agent_execution_tasks", type_="check")
    op.drop_constraint("ck_agent_execution_tasks_attempt_count", "agent_execution_tasks", type_="check")
    op.drop_constraint("ck_agent_execution_tasks_status", "agent_execution_tasks", type_="check")
    op.create_check_constraint(
        "ck_agent_execution_tasks_status",
        "agent_execution_tasks",
        "status IN ('pending','running','waiting_approval','completed','failed','cancelled')",
    )
    op.drop_index("ix_agent_execution_tasks_scheduled_at", table_name="agent_execution_tasks")
    op.drop_index("ix_agent_execution_tasks_depends_on_task_id", table_name="agent_execution_tasks")
    op.drop_constraint("fk_agent_execution_tasks_depends_on_task_id", "agent_execution_tasks", type_="foreignkey")
    op.drop_column("agent_execution_tasks", "last_error_message")
    op.drop_column("agent_execution_tasks", "last_error_code")
    op.drop_column("agent_execution_tasks", "max_attempts")
    op.drop_column("agent_execution_tasks", "attempt_count")
    op.drop_column("agent_execution_tasks", "scheduled_at")
    op.drop_column("agent_execution_tasks", "depends_on_task_id")

    op.drop_constraint("ck_agent_executions_duration_ms", "agent_executions", type_="check")
    op.drop_constraint("ck_agent_executions_token_output_count", "agent_executions", type_="check")
    op.drop_constraint("ck_agent_executions_token_input_count", "agent_executions", type_="check")
    op.drop_constraint("ck_agent_executions_timeout_seconds", "agent_executions", type_="check")
    op.drop_constraint("ck_agent_executions_max_retries", "agent_executions", type_="check")
    op.drop_constraint("ck_agent_executions_retry_count", "agent_executions", type_="check")
    op.drop_constraint("ck_agent_executions_status", "agent_executions", type_="check")
    op.create_check_constraint(
        "ck_agent_executions_status",
        "agent_executions",
        "status IN ('queued','running','waiting_approval','completed','failed','cancelled')",
    )
    op.drop_constraint("uq_agent_executions_org_agent_idempotency", "agent_executions", type_="unique")
    op.drop_column("agent_executions", "last_error_message")
    op.drop_column("agent_executions", "last_error_code")
    op.drop_column("agent_executions", "duration_ms")
    op.drop_column("agent_executions", "token_output_count")
    op.drop_column("agent_executions", "token_input_count")
    op.drop_column("agent_executions", "next_retry_at")
    op.drop_column("agent_executions", "retry_count")
    op.drop_column("agent_executions", "max_retries")
    op.drop_column("agent_executions", "timeout_seconds")
    op.drop_column("agent_executions", "idempotency_key")

    op.execute("UPDATE agent_executions SET status = 'completed' WHERE status = 'succeeded'")
    op.execute("UPDATE agent_execution_tasks SET status = 'completed' WHERE status = 'succeeded'")
