from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_conversations_org_id"),
        Index("ix_conversations_org_project_updated", "organization_id", "project_id", "updated_at"),
        Index("ix_conversations_org_status_updated", "organization_id", "status", "updated_at"),
        CheckConstraint("status IN ('draft','active','processing','waiting_approval','completed','failed','cancelled')", name="ck_conversations_status"),
        CheckConstraint("state_version >= 1", name="ck_conversations_state_version"),
        ForeignKeyConstraint(["organization_id", "project_id"], ["projects.organization_id", "projects.id"], ondelete="RESTRICT"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationMember(Base):
    __tablename__ = "conversation_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_conversation_members_org_id"),
        UniqueConstraint("organization_id", "conversation_id", "user_id", name="uq_conversation_members_org_conversation_user"),
        UniqueConstraint("organization_id", "conversation_id", "agent_profile_id", name="uq_conversation_members_org_conversation_agent"),
        Index("ix_conversation_members_org_conversation", "organization_id", "conversation_id"),
        CheckConstraint("member_type IN ('user','agent')", name="ck_conversation_members_type"),
        CheckConstraint("membership_role IN ('owner','participant','observer','supervisor')", name="ck_conversation_members_role"),
        CheckConstraint("(member_type = 'user' AND user_id IS NOT NULL AND agent_profile_id IS NULL) OR (member_type = 'agent' AND user_id IS NULL AND agent_profile_id IS NOT NULL)", name="ck_conversation_members_exclusive_identity"),
        ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["organization_id", "agent_profile_id"], ["agent_profiles.organization_id", "agent_profiles.id"], ondelete="RESTRICT"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    member_type: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    agent_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    membership_role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="participant")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_conversation_messages_org_id"),
        UniqueConstraint("organization_id", "conversation_id", "sequence_number", name="uq_conversation_messages_org_conversation_sequence"),
        UniqueConstraint("organization_id", "conversation_id", "idempotency_key", name="uq_conversation_messages_org_conversation_idempotency"),
        Index("ix_conversation_messages_org_conversation", "organization_id", "conversation_id"),
        CheckConstraint("sender_type IN ('user','agent','system')", name="ck_conversation_messages_sender_type"),
        CheckConstraint("message_type IN ('user_message','agent_progress','agent_result','system_event','approval_notice','error_notice')", name="ck_conversation_messages_type"),
        CheckConstraint("data_classification IN ('public','internal','sensitive','potential_patient_identifying')", name="ck_conversation_messages_classification"),
        CheckConstraint("(sender_type = 'user' AND sender_user_id IS NOT NULL AND sender_agent_profile_id IS NULL) OR (sender_type = 'agent' AND sender_user_id IS NULL AND sender_agent_profile_id IS NOT NULL) OR (sender_type = 'system' AND sender_user_id IS NULL AND sender_agent_profile_id IS NULL)", name="ck_conversation_messages_exclusive_sender"),
        ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["organization_id", "sender_agent_profile_id"], ["agent_profiles.organization_id", "agent_profiles.id"], ondelete="RESTRICT"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    sender_agent_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    data_classification: Mapped[str] = mapped_column(String(40), nullable=False, server_default="internal")
    encryption_key_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConversationTask(Base):
    __tablename__ = "conversation_tasks"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_conversation_tasks_org_id"),
        UniqueConstraint("organization_id", "conversation_id", "id", name="uq_conversation_tasks_org_conversation_id"),
        UniqueConstraint("organization_id", "conversation_id", "task_key", name="uq_conversation_tasks_org_conversation_key"),
        CheckConstraint("status IN ('planned','waiting_dependency','waiting_approval','queued','running','completed','failed','cancelled')", name="ck_conversation_tasks_status"),
        CheckConstraint("state_version >= 1", name="ck_conversation_tasks_state_version"),
        ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["organization_id", "agent_profile_id"], ["agent_profiles.organization_id", "agent_profiles.id"], ondelete="RESTRICT"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_key: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="planned")
    is_high_impact: Mapped[bool] = mapped_column(nullable=False, server_default="0")
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SupervisorPlan(Base):
    __tablename__ = "supervisor_plans"
    __table_args__ = (
        UniqueConstraint("organization_id", "conversation_id", "plan_version", name="uq_supervisor_plans_org_conversation_version"),
        ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="validated")
    created_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConversationTaskDependency(Base):
    __tablename__ = "conversation_task_dependencies"
    __table_args__ = (
        UniqueConstraint("organization_id", "task_id", "depends_on_task_id", name="uq_conversation_task_dependencies_org_task_dependency"),
        Index("ix_conversation_task_dependencies_org_task", "organization_id", "conversation_id", "task_id"),
        Index("ix_conversation_task_dependencies_org_dependency", "organization_id", "conversation_id", "depends_on_task_id"),
        CheckConstraint("task_id <> depends_on_task_id", name="ck_conversation_task_dependencies_not_self"),
        ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["organization_id", "conversation_id", "task_id"], ["conversation_tasks.organization_id", "conversation_tasks.conversation_id", "conversation_tasks.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["organization_id", "conversation_id", "depends_on_task_id"], ["conversation_tasks.organization_id", "conversation_tasks.conversation_id", "conversation_tasks.id"], ondelete="CASCADE"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    depends_on_task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConversationAuditLog(Base):
    __tablename__ = "conversation_audit_logs"
    __table_args__ = (
        Index("ix_conversation_audit_logs_org_conversation_time", "organization_id", "conversation_id", "created_at"),
        ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
