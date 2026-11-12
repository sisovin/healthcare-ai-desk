"""add agent management foundation schema

Revision ID: 20261112_0006
Revises: 20261112_0005
Create Date: 2026-11-12 10:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20261112_0006"
down_revision: Union[str, None] = "20261112_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_projects_org_id", "projects", ["organization_id", "id"])

    op.create_table(
        "agent_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=80), nullable=True),
        sa.Column("model_provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('draft','active','disabled','archived')", name="ck_agent_profiles_status"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_agent_profiles_org_id"),
        sa.UniqueConstraint("organization_id", "slug", name="uq_agent_profiles_org_slug"),
    )
    op.create_index("ix_agent_profiles_organization_id", "agent_profiles", ["organization_id"], unique=False)
    op.create_index("ix_agent_profiles_created_by_user_id", "agent_profiles", ["created_by_user_id"], unique=False)
    op.create_index("ix_agent_profiles_status", "agent_profiles", ["status"], unique=False)

    op.create_table(
        "agent_project_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("agent_profile_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("assigned_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "agent_profile_id"],
            ["agent_profiles.organization_id", "agent_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "agent_profile_id",
            "project_id",
            name="uq_agent_proj_assignments_org_agent_project",
        ),
    )
    op.create_index(
        "ix_agent_project_assignments_organization_id",
        "agent_project_assignments",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_project_assignments_agent_profile_id",
        "agent_project_assignments",
        ["agent_profile_id"],
        unique=False,
    )
    op.create_index("ix_agent_project_assignments_project_id", "agent_project_assignments", ["project_id"], unique=False)
    op.create_index(
        "ix_agent_project_assignments_assigned_by_user_id",
        "agent_project_assignments",
        ["assigned_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_project_assignments_assigned_by_user_id", table_name="agent_project_assignments")
    op.drop_index("ix_agent_project_assignments_project_id", table_name="agent_project_assignments")
    op.drop_index("ix_agent_project_assignments_agent_profile_id", table_name="agent_project_assignments")
    op.drop_index("ix_agent_project_assignments_organization_id", table_name="agent_project_assignments")
    op.drop_table("agent_project_assignments")

    op.drop_index("ix_agent_profiles_status", table_name="agent_profiles")
    op.drop_index("ix_agent_profiles_created_by_user_id", table_name="agent_profiles")
    op.drop_index("ix_agent_profiles_organization_id", table_name="agent_profiles")
    op.drop_table("agent_profiles")

    op.drop_constraint("uq_projects_org_id", "projects", type_="unique")
