from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import ConversationAuditLog, WorkflowEventConsumption, WorkflowOutboxEvent


def enqueue_message_event(db: Session, *, organization_id: str, conversation_id: str, message_id: str, sequence_number: int, classification: str, correlation_id: str, idempotency_key: str) -> WorkflowOutboxEvent:
    row = WorkflowOutboxEvent(id=str(uuid4()), organization_id=organization_id, conversation_id=conversation_id, aggregate_type="conversation", aggregate_id=conversation_id, event_type="conversation.message_created", event_version=1, payload=json.dumps({"message_id": message_id, "sequence_number": sequence_number, "classification": classification, "correlation_id": correlation_id}, separators=(",", ":")), idempotency_key=f"message:{idempotency_key}")
    db.add(row)
    return row


def lease_events(db: Session, *, publisher_id: str, limit: int = 20, lease_seconds: int = 60) -> list[WorkflowOutboxEvent]:
    now = datetime.now(UTC)
    rows = db.execute(select(WorkflowOutboxEvent).where(or_((WorkflowOutboxEvent.status == "pending") & (WorkflowOutboxEvent.next_attempt_at <= now), (WorkflowOutboxEvent.status == "processing") & (WorkflowOutboxEvent.lease_expires_at <= now))).order_by(WorkflowOutboxEvent.created_at.asc()).limit(limit).with_for_update(skip_locked=True)).scalars().all()
    for row in rows:
        row.status, row.lease_owner, row.lease_expires_at = "processing", publisher_id, now + timedelta(seconds=lease_seconds)
        row.attempt_count += 1
    db.commit()
    return rows


def publish_leased_event(db: Session, *, event_id: str, publisher_id: str, redis_client, stream: str = "healthcare:workflow-events") -> bool:
    # Hold the row lock from lease validation through XADD and state transition.
    # This fences a lease transfer that would otherwise occur after the check but
    # before publication. A process crash can still yield at-least-once delivery;
    # consumers remain idempotent by design.
    row = db.execute(
        select(WorkflowOutboxEvent)
        .where(WorkflowOutboxEvent.id == event_id)
        .with_for_update()
    ).scalar_one_or_none()
    lease_expires_at = row.lease_expires_at if row is not None else None
    if lease_expires_at is not None and lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    if row is None or row.status != "processing" or row.lease_owner != publisher_id or lease_expires_at is None or lease_expires_at <= datetime.now(UTC):
        return False
    try:
        redis_client.xadd(stream, {"event_id": row.id, "organization_id": row.organization_id, "event_type": row.event_type, "payload": row.payload, "idempotency_key": row.idempotency_key})
    except Exception as exc:
        now = datetime.now(UTC)
        row.last_error_code, row.last_error_message = "REDIS_PUBLISH_FAILED", "Redis stream publish failed."
        row.lease_owner, row.lease_expires_at = None, None
        if row.attempt_count >= row.max_attempts:
            row.status = "failed"
        else:
            row.status = "pending"
            row.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(row.attempt_count, 8)))
        # Keep the durable operator audit useful without persisting exception text,
        # connection strings, credentials, or event payload data.
        db.add(ConversationAuditLog(
            id=str(uuid4()), organization_id=row.organization_id, conversation_id=row.conversation_id,
            action="outbox.publish_failed", actor_type="system", actor_id=None,
            correlation_id=None, details=f"event_id={row.id};code=REDIS_PUBLISH_FAILED",
        ))
        db.commit()
        return False
    row.status, row.published_at, row.lease_owner, row.lease_expires_at = "published", datetime.now(UTC), None, None
    db.commit()
    return True


def consume_event(db: Session, *, organization_id: str, event_id: str, consumer_name: str, handler: Callable[[Session, WorkflowOutboxEvent], None]) -> bool:
    event = db.execute(select(WorkflowOutboxEvent).where(WorkflowOutboxEvent.id == event_id, WorkflowOutboxEvent.organization_id == organization_id)).scalar_one_or_none()
    if event is None:
        return False
    db.add(WorkflowEventConsumption(id=str(uuid4()), organization_id=organization_id, event_id=event_id, consumer_name=consumer_name, idempotency_key=event.idempotency_key))
    try:
        db.flush()  # Reserve the unique consumer/event key before any side effect.
    except IntegrityError as exc:
        db.rollback()
        error_text = str(exc.orig)
        is_mysql_duplicate = getattr(exc.orig, "args", [None])[0] == 1062
        is_sqlite_ledger_duplicate = db.bind is not None and db.bind.dialect.name == "sqlite" and "workflow_event_consumptions.organization_id" in error_text
        if (is_mysql_duplicate and "uq_workflow_event_consumptions_org_event_consumer" in error_text) or is_sqlite_ledger_duplicate:
            return False
        raise
    try:
        handler(db, event)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True


def ack_after_commit(redis_client, *, stream: str, group: str, entry_id: str) -> None:
    redis_client.xack(stream, group, entry_id)


def reclaim_pending_entries(redis_client, *, stream: str, group: str, consumer: str, min_idle_ms: int = 60_000, start_id: str = "0-0", count: int = 100):
    """Claim idle consumer-group entries; callers still deduplicate before effects."""
    result = redis_client.xautoclaim(stream, group, consumer, min_idle_ms, start_id, count=count)
    if isinstance(result, (tuple, list)) and len(result) >= 2 and isinstance(result[1], (tuple, list)):
        return result[1]
    return result


def replay_failed_event(db: Session, *, organization_id: str, event_id: str, actor_user_id: str) -> WorkflowOutboxEvent | None:
    row = db.execute(select(WorkflowOutboxEvent).where(WorkflowOutboxEvent.id == event_id, WorkflowOutboxEvent.organization_id == organization_id)).scalar_one_or_none()
    if row is None or row.status != "failed": return None
    row.status, row.next_attempt_at, row.lease_owner, row.lease_expires_at, row.last_error_code, row.last_error_message = "pending", datetime.now(UTC), None, None, None, None
    db.add(ConversationAuditLog(id=str(uuid4()), organization_id=organization_id, conversation_id=row.conversation_id, action="outbox.failed_event_replayed", actor_type="user", actor_id=actor_user_id, correlation_id=None, details=f"event_id={row.id}"))
    db.commit(); db.refresh(row)
    return row


def backlog_metrics(db: Session, *, organization_id: str) -> dict[str, int]:
    rows = db.execute(select(WorkflowOutboxEvent.status, func.count()).where(WorkflowOutboxEvent.organization_id == organization_id).group_by(WorkflowOutboxEvent.status)).all()
    counts = {status: count for status, count in rows}
    return {"pending": counts.get("pending", 0), "processing": counts.get("processing", 0), "published": counts.get("published", 0), "failed": counts.get("failed", 0)}
