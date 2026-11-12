"""M3.2.1 Phase-A shared timeline allocator.

This module is intentionally not wired into a live write path until migration
execution and cutover approval. It documents the only permitted allocation
algorithm for user and protocol message writers after cutover.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


MAX_ALLOCATABLE_SEQUENCE = 2_147_483_646


class TimelineCapacityError(Exception):
    pass


def allocate_next_timeline_sequence(db: Session, *, organization_id: str, conversation_id: str) -> int:
    """Lock and reserve a sequence in the caller-owned transaction.

    This function never commits or rolls back. Its caller must insert the
    message/audit/outbox rows, then commit once; any exception requires caller
    rollback before the session is reused.
    """
    row = db.execute(
        text(
            "SELECT next_timeline_sequence FROM conversations "
            "WHERE organization_id = :organization_id AND id = :conversation_id FOR UPDATE"
        ),
        {"organization_id": organization_id, "conversation_id": conversation_id},
    ).mappings().one_or_none()
    if row is None:
        raise LookupError("Conversation not found.")
    sequence = int(row["next_timeline_sequence"])
    if sequence > MAX_ALLOCATABLE_SEQUENCE:
        raise TimelineCapacityError("Conversation timeline sequence capacity is exhausted.")
    db.execute(
        text(
            "UPDATE conversations SET next_timeline_sequence = :next_sequence "
            "WHERE organization_id = :organization_id AND id = :conversation_id"
        ),
        {"next_sequence": sequence + 1, "organization_id": organization_id, "conversation_id": conversation_id},
    )
    return sequence
