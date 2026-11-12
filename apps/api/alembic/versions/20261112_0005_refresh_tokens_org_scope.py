"""scope refresh tokens to organization

Revision ID: 20261112_0005
Revises: 20261112_0004
Create Date: 2026-11-12 09:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20261112_0005"
down_revision: Union[str, None] = "20261112_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("organization_id", sa.String(length=36), nullable=True))
    op.add_column("refresh_tokens", sa.Column("revoked_reason", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        "fk_refresh_tokens_organization_id",
        "refresh_tokens",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_refresh_tokens_organization_id", "refresh_tokens", ["organization_id"], unique=False)
    op.create_index(
        "ix_refresh_tokens_user_org_active",
        "refresh_tokens",
        ["user_id", "organization_id", "revoked_at"],
        unique=False,
    )

    op.execute(
        "UPDATE refresh_tokens "
        "SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP), "
        "revoked_reason = COALESCE(revoked_reason, 'legacy_unscoped_token') "
        "WHERE organization_id IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_org_active", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_organization_id", table_name="refresh_tokens")
    op.drop_constraint("fk_refresh_tokens_organization_id", "refresh_tokens", type_="foreignkey")
    op.drop_column("refresh_tokens", "revoked_reason")
    op.drop_column("refresh_tokens", "organization_id")
