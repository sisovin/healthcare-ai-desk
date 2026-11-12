"""add M3.1.2 transactional outbox

Revision ID: 20261112_0010
Revises: 20261112_0009
Create Date: 2026-11-12 21:30:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20261112_0010"
down_revision: Union[str, None] = "20261112_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table("workflow_outbox_events",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), nullable=False), sa.Column("conversation_id", sa.String(36), nullable=False), sa.Column("aggregate_type", sa.String(64), nullable=False), sa.Column("aggregate_id", sa.String(36), nullable=False), sa.Column("event_type", sa.String(100), nullable=False), sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"), sa.Column("payload", sa.Text(), nullable=False), sa.Column("status", sa.String(16), nullable=False, server_default="pending"), sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"), sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("lease_owner", sa.String(128)), sa.Column("lease_expires_at", sa.DateTime(timezone=True)), sa.Column("last_error_code", sa.String(64)), sa.Column("last_error_message", sa.Text()), sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("organization_id", "id", name="uq_workflow_outbox_events_org_id"), sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_outbox_events_org_idempotency"), sa.CheckConstraint("status IN ('pending','processing','published','failed')", name="ck_workflow_outbox_events_status"), sa.CheckConstraint("attempt_count >= 0", name="ck_workflow_outbox_events_attempt_count"), sa.CheckConstraint("max_attempts >= 1", name="ck_workflow_outbox_events_max_attempts"), sa.ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"))
    op.create_index("ix_workflow_outbox_events_status_schedule_lease", "workflow_outbox_events", ["status", "next_attempt_at", "lease_expires_at"])
    op.create_index("ix_workflow_outbox_events_org_conversation_time", "workflow_outbox_events", ["organization_id", "conversation_id", "created_at"])
    op.create_table("workflow_event_consumptions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), nullable=False), sa.Column("event_id", sa.String(36), nullable=False), sa.Column("consumer_name", sa.String(100), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("organization_id", "event_id", "consumer_name", name="uq_workflow_event_consumptions_org_event_consumer"), sa.ForeignKeyConstraint(["organization_id", "event_id"], ["workflow_outbox_events.organization_id", "workflow_outbox_events.id"], ondelete="CASCADE"))
    op.create_index("ix_workflow_event_consumptions_org_consumer_time", "workflow_event_consumptions", ["organization_id", "consumer_name", "created_at"])

def downgrade() -> None:
    op.drop_table("workflow_event_consumptions"); op.drop_table("workflow_outbox_events")
