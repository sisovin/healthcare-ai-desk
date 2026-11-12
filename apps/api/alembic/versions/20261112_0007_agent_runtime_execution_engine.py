"""add agent runtime and execution engine schema

Revision ID: 20261112_0007
Revises: 20261112_0006
Create Date: 2026-11-12 11:15:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20261112_0007"
down_revision: Union[str, None] = "20261112_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("agent_profile_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("snapshot_name", sa.String(length=120), nullable=False),
        sa.Column("snapshot_role", sa.String(length=80), nullable=True),
        sa.Column("snapshot_model_provider", sa.String(length=64), nullable=False),
        sa.Column("snapshot_model_name", sa.String(length=128), nullable=False),
        sa.Column("snapshot_system_prompt", sa.Text(), nullable=True),
        sa.Column("published_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("version_number >= 1", name="ck_agent_versions_version_number"),
        sa.ForeignKeyConstraint(
            ["organization_id", "agent_profile_id"],
            ["agent_profiles.organization_id", "agent_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_agent_versions_org_id"),
        sa.UniqueConstraint(
            "organization_id",
            "agent_profile_id",
            "version_number",
            name="uq_agent_versions_org_agent_number",
        ),
    )
    op.create_index("ix_agent_versions_organization_id", "agent_versions", ["organization_id"], unique=False)
    op.create_index("ix_agent_versions_agent_profile_id", "agent_versions", ["agent_profile_id"], unique=False)
    op.create_index("ix_agent_versions_is_published", "agent_versions", ["is_published"], unique=False)
    op.create_index("ix_agent_versions_published_by_user_id", "agent_versions", ["published_by_user_id"], unique=False)

    op.create_table(
        "agent_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("agent_profile_id", sa.String(length=36), nullable=False),
        sa.Column("agent_version_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("input_payload", sa.Text(), nullable=True),
        sa.Column("result_payload", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','waiting_approval','completed','failed','cancelled')",
            name="ck_agent_executions_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "agent_profile_id"],
            ["agent_profiles.organization_id", "agent_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "agent_version_id"],
            ["agent_versions.organization_id", "agent_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_agent_executions_org_id"),
    )
    op.create_index("ix_agent_executions_organization_id", "agent_executions", ["organization_id"], unique=False)
    op.create_index("ix_agent_executions_agent_profile_id", "agent_executions", ["agent_profile_id"], unique=False)
    op.create_index("ix_agent_executions_agent_version_id", "agent_executions", ["agent_version_id"], unique=False)
    op.create_index("ix_agent_executions_requested_by_user_id", "agent_executions", ["requested_by_user_id"], unique=False)
    op.create_index("ix_agent_executions_project_id", "agent_executions", ["project_id"], unique=False)
    op.create_index("ix_agent_executions_status", "agent_executions", ["status"], unique=False)

    op.create_table(
        "agent_execution_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("queue_position", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("task_payload", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("queue_position >= 1", name="ck_agent_execution_tasks_queue_position"),
        sa.CheckConstraint(
            "status IN ('pending','running','waiting_approval','completed','failed','cancelled')",
            name="ck_agent_execution_tasks_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "execution_id"],
            ["agent_executions.organization_id", "agent_executions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_agent_execution_tasks_org_id"),
        sa.UniqueConstraint(
            "organization_id",
            "execution_id",
            "queue_position",
            name="uq_agent_execution_tasks_org_execution_position",
        ),
    )
    op.create_index("ix_agent_execution_tasks_organization_id", "agent_execution_tasks", ["organization_id"], unique=False)
    op.create_index("ix_agent_execution_tasks_execution_id", "agent_execution_tasks", ["execution_id"], unique=False)
    op.create_index("ix_agent_execution_tasks_status", "agent_execution_tasks", ["status"], unique=False)

    op.create_table(
        "agent_execution_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "execution_id"],
            ["agent_executions.organization_id", "agent_executions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_execution_audit_logs_organization_id", "agent_execution_audit_logs", ["organization_id"], unique=False)
    op.create_index("ix_agent_execution_audit_logs_execution_id", "agent_execution_audit_logs", ["execution_id"], unique=False)
    op.create_index("ix_agent_execution_audit_logs_action", "agent_execution_audit_logs", ["action"], unique=False)
    op.create_index("ix_agent_execution_audit_logs_actor_user_id", "agent_execution_audit_logs", ["actor_user_id"], unique=False)

    op.create_table(
        "agent_execution_approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewer_user_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending','approved','rejected')", name="ck_agent_execution_approvals_status"),
        sa.ForeignKeyConstraint(
            ["organization_id", "execution_id"],
            ["agent_executions.organization_id", "agent_executions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_agent_execution_approvals_org_id"),
    )
    op.create_index("ix_agent_execution_approvals_organization_id", "agent_execution_approvals", ["organization_id"], unique=False)
    op.create_index("ix_agent_execution_approvals_execution_id", "agent_execution_approvals", ["execution_id"], unique=False)
    op.create_index("ix_agent_execution_approvals_requested_by_user_id", "agent_execution_approvals", ["requested_by_user_id"], unique=False)
    op.create_index("ix_agent_execution_approvals_reviewer_user_id", "agent_execution_approvals", ["reviewer_user_id"], unique=False)
    op.create_index("ix_agent_execution_approvals_status", "agent_execution_approvals", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_execution_approvals_status", table_name="agent_execution_approvals")
    op.drop_index("ix_agent_execution_approvals_reviewer_user_id", table_name="agent_execution_approvals")
    op.drop_index("ix_agent_execution_approvals_requested_by_user_id", table_name="agent_execution_approvals")
    op.drop_index("ix_agent_execution_approvals_execution_id", table_name="agent_execution_approvals")
    op.drop_index("ix_agent_execution_approvals_organization_id", table_name="agent_execution_approvals")
    op.drop_table("agent_execution_approvals")

    op.drop_index("ix_agent_execution_audit_logs_actor_user_id", table_name="agent_execution_audit_logs")
    op.drop_index("ix_agent_execution_audit_logs_action", table_name="agent_execution_audit_logs")
    op.drop_index("ix_agent_execution_audit_logs_execution_id", table_name="agent_execution_audit_logs")
    op.drop_index("ix_agent_execution_audit_logs_organization_id", table_name="agent_execution_audit_logs")
    op.drop_table("agent_execution_audit_logs")

    op.drop_index("ix_agent_execution_tasks_status", table_name="agent_execution_tasks")
    op.drop_index("ix_agent_execution_tasks_execution_id", table_name="agent_execution_tasks")
    op.drop_index("ix_agent_execution_tasks_organization_id", table_name="agent_execution_tasks")
    op.drop_table("agent_execution_tasks")

    op.drop_index("ix_agent_executions_status", table_name="agent_executions")
    op.drop_index("ix_agent_executions_project_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_requested_by_user_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_agent_version_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_agent_profile_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_organization_id", table_name="agent_executions")
    op.drop_table("agent_executions")

    op.drop_index("ix_agent_versions_published_by_user_id", table_name="agent_versions")
    op.drop_index("ix_agent_versions_is_published", table_name="agent_versions")
    op.drop_index("ix_agent_versions_agent_profile_id", table_name="agent_versions")
    op.drop_index("ix_agent_versions_organization_id", table_name="agent_versions")
    op.drop_table("agent_versions")
