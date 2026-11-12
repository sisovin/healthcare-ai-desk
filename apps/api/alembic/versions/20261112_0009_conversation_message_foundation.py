"""add M3.1.1 conversation and message foundation

Revision ID: 20261112_0009
Revises: 20261112_0008
Create Date: 2026-11-12 20:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261112_0009"
down_revision: Union[str, None] = "20261112_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False), sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "id", name="uq_conversations_org_id"),
        sa.CheckConstraint("status IN ('draft','active','processing','waiting_approval','completed','failed','cancelled')", name="ck_conversations_status"), sa.CheckConstraint("state_version >= 1", name="ck_conversations_state_version"),
        sa.ForeignKeyConstraint(["organization_id", "project_id"], ["projects.organization_id", "projects.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_conversations_org_project_updated", "conversations", ["organization_id", "project_id", "updated_at"])
    op.create_index("ix_conversations_org_status_updated", "conversations", ["organization_id", "status", "updated_at"])
    op.create_table(
        "conversation_members",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), nullable=False), sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("member_type", sa.String(16), nullable=False), sa.Column("user_id", sa.String(36)), sa.Column("agent_profile_id", sa.String(36)), sa.Column("membership_role", sa.String(16), nullable=False, server_default="participant"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "id", name="uq_conversation_members_org_id"), sa.UniqueConstraint("organization_id", "conversation_id", "user_id", name="uq_conversation_members_org_conversation_user"), sa.UniqueConstraint("organization_id", "conversation_id", "agent_profile_id", name="uq_conversation_members_org_conversation_agent"),
        sa.CheckConstraint("member_type IN ('user','agent')", name="ck_conversation_members_type"), sa.CheckConstraint("membership_role IN ('owner','participant','observer','supervisor')", name="ck_conversation_members_role"), sa.CheckConstraint("(member_type = 'user' AND user_id IS NOT NULL AND agent_profile_id IS NULL) OR (member_type = 'agent' AND user_id IS NULL AND agent_profile_id IS NOT NULL)", name="ck_conversation_members_exclusive_identity"),
        sa.ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["organization_id", "agent_profile_id"], ["agent_profiles.organization_id", "agent_profiles.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_conversation_members_org_conversation", "conversation_members", ["organization_id", "conversation_id"])
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), nullable=False), sa.Column("conversation_id", sa.String(36), nullable=False), sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("sender_type", sa.String(16), nullable=False), sa.Column("sender_user_id", sa.String(36)), sa.Column("sender_agent_profile_id", sa.String(36)), sa.Column("message_type", sa.String(32), nullable=False),
        sa.Column("content_ciphertext", sa.Text()), sa.Column("content_redacted", sa.Text(), nullable=False), sa.Column("data_classification", sa.String(40), nullable=False, server_default="internal"), sa.Column("encryption_key_ref", sa.String(128)), sa.Column("retention_expires_at", sa.DateTime(timezone=True)), sa.Column("payload_metadata", sa.Text()),
        sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("request_fingerprint", sa.String(64), nullable=False), sa.Column("correlation_id", sa.String(36), nullable=False), sa.Column("causation_id", sa.String(36)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("organization_id", "id", name="uq_conversation_messages_org_id"), sa.UniqueConstraint("organization_id", "conversation_id", "sequence_number", name="uq_conversation_messages_org_conversation_sequence"), sa.UniqueConstraint("organization_id", "conversation_id", "idempotency_key", name="uq_conversation_messages_org_conversation_idempotency"),
        sa.CheckConstraint("sender_type IN ('user','agent','system')", name="ck_conversation_messages_sender_type"), sa.CheckConstraint("message_type IN ('user_message','agent_progress','agent_result','system_event','approval_notice','error_notice')", name="ck_conversation_messages_type"), sa.CheckConstraint("data_classification IN ('public','internal','sensitive','potential_patient_identifying')", name="ck_conversation_messages_classification"), sa.CheckConstraint("(sender_type = 'user' AND sender_user_id IS NOT NULL AND sender_agent_profile_id IS NULL) OR (sender_type = 'agent' AND sender_user_id IS NULL AND sender_agent_profile_id IS NOT NULL) OR (sender_type = 'system' AND sender_user_id IS NULL AND sender_agent_profile_id IS NULL)", name="ck_conversation_messages_exclusive_sender"),
        sa.ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["organization_id", "sender_agent_profile_id"], ["agent_profiles.organization_id", "agent_profiles.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_conversation_messages_org_conversation", "conversation_messages", ["organization_id", "conversation_id"])
    op.create_table(
        "conversation_tasks",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), nullable=False), sa.Column("conversation_id", sa.String(36), nullable=False), sa.Column("task_key", sa.String(100), nullable=False), sa.Column("agent_profile_id", sa.String(36)), sa.Column("agent_version_id", sa.String(36)), sa.Column("execution_id", sa.String(36)), sa.Column("task_type", sa.String(64), nullable=False), sa.Column("status", sa.String(32), nullable=False, server_default="planned"), sa.Column("is_high_impact", sa.Boolean(), nullable=False, server_default=sa.text("0")), sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"), sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("organization_id", "id", name="uq_conversation_tasks_org_id"), sa.UniqueConstraint("organization_id", "conversation_id", "id", name="uq_conversation_tasks_org_conversation_id"), sa.UniqueConstraint("organization_id", "conversation_id", "task_key", name="uq_conversation_tasks_org_conversation_key"), sa.CheckConstraint("status IN ('planned','waiting_dependency','waiting_approval','queued','running','completed','failed','cancelled')", name="ck_conversation_tasks_status"), sa.CheckConstraint("state_version >= 1", name="ck_conversation_tasks_state_version"),
        sa.ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["organization_id", "agent_profile_id"], ["agent_profiles.organization_id", "agent_profiles.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "conversation_task_dependencies",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), nullable=False), sa.Column("conversation_id", sa.String(36), nullable=False), sa.Column("task_id", sa.String(36), nullable=False), sa.Column("depends_on_task_id", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("organization_id", "task_id", "depends_on_task_id", name="uq_conversation_task_dependencies_org_task_dependency"), sa.CheckConstraint("task_id <> depends_on_task_id", name="ck_conversation_task_dependencies_not_self"),
        sa.ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["organization_id", "conversation_id", "task_id"], ["conversation_tasks.organization_id", "conversation_tasks.conversation_id", "conversation_tasks.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["organization_id", "conversation_id", "depends_on_task_id"], ["conversation_tasks.organization_id", "conversation_tasks.conversation_id", "conversation_tasks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_conversation_task_dependencies_org_task", "conversation_task_dependencies", ["organization_id", "conversation_id", "task_id"])
    op.create_index("ix_conversation_task_dependencies_org_dependency", "conversation_task_dependencies", ["organization_id", "conversation_id", "depends_on_task_id"])
    op.create_table(
        "conversation_audit_logs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), nullable=False), sa.Column("conversation_id", sa.String(36), nullable=False), sa.Column("action", sa.String(100), nullable=False), sa.Column("actor_type", sa.String(32), nullable=False), sa.Column("actor_id", sa.String(36)), sa.Column("correlation_id", sa.String(36)), sa.Column("metadata", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_conversation_audit_logs_org_conversation_time", "conversation_audit_logs", ["organization_id", "conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_table("conversation_audit_logs"); op.drop_table("conversation_task_dependencies"); op.drop_table("conversation_tasks"); op.drop_table("conversation_messages"); op.drop_table("conversation_members"); op.drop_table("conversations")
