"""add M3.2.1 protocol message contract

Phase-A source only: do not apply to the shared local database until the
M3.2.1 pre-execution verification gate has been approved.

Revision ID: 20261112_0012
Revises: 20261112_0011
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261112_0012"
down_revision: Union[str, None] = "20261112_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cutover protocol requires all timeline writers quiesced before this backfill.
    bind = op.get_bind()
    overflow_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT MAX(sequence_number) AS max_sequence "
            "FROM conversation_messages GROUP BY organization_id, conversation_id) AS sequences "
            "WHERE max_sequence >= 2147483647"
        )
    ).scalar_one()
    if overflow_count:
        raise RuntimeError("M3.2.1 cannot allocate a signed INTEGER timeline counter for an exhausted conversation.")

    for table_name, index_name in (("conversations", "uq_conversations_org_id"), ("agent_profiles", "uq_agent_profiles_org_id")):
        index_columns = bind.execute(
            sa.text(
                "SELECT column_name FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = :table_name AND index_name = :index_name "
                "ORDER BY seq_in_index"
            ),
            {"table_name": table_name, "index_name": index_name},
        ).scalars().all()
        if index_columns != ["organization_id", "id"]:
            raise RuntimeError(f"M3.2.1 requires {table_name}.{index_name} to be (organization_id, id).")
        uuid_columns = bind.execute(
            sa.text(
                "SELECT column_name, character_maximum_length, collation_name FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = :table_name "
                "AND column_name IN ('organization_id', 'id') ORDER BY column_name"
            ),
            {"table_name": table_name},
        ).all()
        if any(length != 36 or collation != "utf8mb4_unicode_ci" for _name, length, collation in uuid_columns) or len(uuid_columns) != 2:
            raise RuntimeError(f"M3.2.1 UUID FK compatibility preflight failed for {table_name}.")

    op.add_column(
        "conversations",
        sa.Column("next_timeline_sequence", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE conversations c
        LEFT JOIN (
            SELECT organization_id, conversation_id, MAX(sequence_number) AS max_sequence
            FROM conversation_messages
            GROUP BY organization_id, conversation_id
        ) m ON m.organization_id = c.organization_id AND m.conversation_id = c.id
        SET c.next_timeline_sequence = COALESCE(m.max_sequence, 0) + 1
        """
    )
    invalid_backfill_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM conversations c LEFT JOIN ("
            "SELECT organization_id, conversation_id, MAX(sequence_number) AS max_sequence "
            "FROM conversation_messages GROUP BY organization_id, conversation_id"
            ") m ON m.organization_id = c.organization_id AND m.conversation_id = c.id "
            "WHERE c.next_timeline_sequence <> COALESCE(m.max_sequence, 0) + 1 "
            "OR c.next_timeline_sequence IS NULL "
            "OR c.next_timeline_sequence < 1 OR c.next_timeline_sequence > 2147483647"
        )
    ).scalar_one()
    if invalid_backfill_count:
        raise RuntimeError("M3.2.1 timeline counter backfill postcondition failed.")
    op.create_check_constraint(
        "ck_conversations_next_timeline_sequence",
        "conversations",
        "next_timeline_sequence >= 1 AND next_timeline_sequence <= 2147483647",
    )
    op.alter_column("conversations", "next_timeline_sequence", existing_type=sa.Integer(), nullable=False, server_default=sa.text("1"))
    op.create_table(
        "conversation_protocol_messages",
        sa.Column("id", sa.String(36, collation="utf8mb4_unicode_ci"), primary_key=True),
        sa.Column("organization_id", sa.String(36, collation="utf8mb4_unicode_ci"), nullable=False),
        sa.Column("conversation_id", sa.String(36, collation="utf8mb4_unicode_ci"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("sender_type", sa.String(16), nullable=False, server_default="agent"),
        sa.Column("sender_agent_profile_id", sa.String(36, collation="utf8mb4_unicode_ci"), nullable=False),
        sa.Column("recipient_type", sa.String(16), nullable=False),
        sa.Column("recipient_agent_profile_id", sa.String(36, collation="utf8mb4_unicode_ci"), nullable=True),
        sa.Column("message_type", sa.String(32), nullable=False),
        sa.Column("payload_ciphertext", sa.Text(), nullable=True),
        sa.Column("payload_redacted", sa.Text(), nullable=False),
        sa.Column("data_classification", sa.String(40), nullable=False, server_default="internal"),
        sa.Column("encryption_key_ref", sa.String(128), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("causation_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("organization_id", "id", name="uq_conversation_protocol_messages_org_id"),
        sa.UniqueConstraint("organization_id", "conversation_id", "sequence_number", name="uq_conversation_protocol_messages_org_conversation_sequence"),
        sa.UniqueConstraint("organization_id", "conversation_id", "idempotency_key", name="uq_conversation_protocol_messages_org_conversation_idempotency"),
        sa.CheckConstraint("sender_type = 'agent'", name="ck_conversation_protocol_messages_sender_type"),
        sa.CheckConstraint("recipient_type IN ('agent','supervisor','conversation')", name="ck_conversation_protocol_messages_recipient_type"),
        sa.CheckConstraint("(recipient_type = 'agent' AND recipient_agent_profile_id IS NOT NULL) OR (recipient_type IN ('supervisor','conversation') AND recipient_agent_profile_id IS NULL)", name="ck_conversation_protocol_messages_recipient_identity"),
        sa.CheckConstraint("message_type IN ('task_assigned','agent_progress','agent_result','approval_requested','approval_decided','task_failed','conversation_started','conversation_completed','conversation_cancelled')", name="ck_conversation_protocol_messages_type"),
        sa.CheckConstraint("data_classification IN ('public','internal','sensitive','potential_patient_identifying')", name="ck_conversation_protocol_messages_classification"),
        sa.ForeignKeyConstraint(["organization_id", "conversation_id"], ["conversations.organization_id", "conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id", "sender_agent_profile_id"], ["agent_profiles.organization_id", "agent_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id", "recipient_agent_profile_id"], ["agent_profiles.organization_id", "agent_profiles.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_conversation_protocol_messages_org_conversation_time", "conversation_protocol_messages", ["organization_id", "conversation_id", "created_at"])
    op.create_index("ix_conversation_protocol_messages_org_recipient_time", "conversation_protocol_messages", ["organization_id", "recipient_type", "recipient_agent_profile_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError("M3.2.1 is forward-only. Use the reviewed forward-recovery procedure.")
