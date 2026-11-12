"""add M3.1.3 supervisor plans

Revision ID: 20261112_0011
Revises: 20261112_0010
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "20261112_0011"
down_revision: Union[str, None] = "20261112_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
def upgrade() -> None:
    op.create_table("supervisor_plans", sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), nullable=False), sa.Column("conversation_id", sa.String(36), nullable=False), sa.Column("plan_version", sa.Integer(), nullable=False), sa.Column("plan_json", sa.Text(), nullable=False), sa.Column("status", sa.String(32), nullable=False, server_default="validated"), sa.Column("created_by_user_id", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.UniqueConstraint("organization_id", "conversation_id", "plan_version", name="uq_supervisor_plans_org_conversation_version"), sa.ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"))
def downgrade() -> None: op.drop_table("supervisor_plans")
