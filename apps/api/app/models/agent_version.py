from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_agent_versions_org_id"),
        UniqueConstraint("organization_id", "agent_profile_id", "version_number", name="uq_agent_versions_org_agent_number"),
        CheckConstraint("version_number >= 1", name="ck_agent_versions_version_number"),
        ForeignKeyConstraint(
            ["organization_id", "agent_profile_id"],
            ["agent_profiles.organization_id", "agent_profiles.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", index=True)
    snapshot_name: Mapped[str] = mapped_column(String(120), nullable=False)
    snapshot_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    snapshot_model_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
