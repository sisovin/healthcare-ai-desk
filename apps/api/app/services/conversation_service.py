from __future__ import annotations

import base64
from datetime import UTC, datetime
from hashlib import sha256
import re
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Conversation, ConversationAuditLog, ConversationMember, ConversationMessage, Project
from app.services.outbox_service import enqueue_message_event


class ConversationNotFoundError(Exception): pass
class ConversationValidationError(Exception): pass
class ConversationConflictError(Exception): pass


_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?855|0)\d{8,10}(?!\d)")
_PATIENT_KEY = re.compile(r'(?i)\b(patient[_ -]?id|mrn|medical[_ -]?record(?:[_ -]?number)?|national[_ -]?id|nhis[_ -]?id)\b["\']?\s*[:=]\s*["\']?[^,}\s"\']+')


def _fernet() -> Fernet:
    material = getattr(settings, "conversation_encryption_key", "") or settings.app_secret_key
    key = base64.urlsafe_b64encode(sha256(material.encode("utf-8")).digest())
    return Fernet(key)


def _redact_and_classify(content: str) -> tuple[str, str]:
    redacted = _EMAIL.sub("[REDACTED_EMAIL]", content)
    redacted = _PHONE.sub("[REDACTED_PHONE]", redacted)
    redacted = _PATIENT_KEY.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return redacted, "potential_patient_identifying" if redacted != content else "internal"


def _audit(db: Session, *, organization_id: str, conversation_id: str, action: str, actor_id: str, correlation_id: str | None, metadata: str | None) -> None:
    db.add(ConversationAuditLog(id=str(uuid4()), organization_id=organization_id, conversation_id=conversation_id, action=action, actor_type="user", actor_id=actor_id, correlation_id=correlation_id, details=metadata))


def create_conversation(db: Session, *, organization_id: str, project_id: str, title: str, actor_user_id: str) -> Conversation:
    project = db.execute(select(Project).where(Project.id == project_id, Project.organization_id == organization_id)).scalar_one_or_none()
    if project is None:
        raise ConversationNotFoundError("Project not found.")
    row = Conversation(id=str(uuid4()), organization_id=organization_id, project_id=project_id, created_by_user_id=actor_user_id, title=title.strip(), status="active")
    db.add(row)
    db.flush()
    db.add(ConversationMember(id=str(uuid4()), organization_id=organization_id, conversation_id=row.id, member_type="user", user_id=actor_user_id, membership_role="owner"))
    _audit(db, organization_id=organization_id, conversation_id=row.id, action="conversation.created", actor_id=actor_user_id, correlation_id=None, metadata="project_scoped")
    db.commit(); db.refresh(row)
    return row


def get_conversation(db: Session, *, organization_id: str, conversation_id: str, user_id: str) -> Conversation | None:
    return db.execute(select(Conversation).join(ConversationMember, (ConversationMember.conversation_id == Conversation.id) & (ConversationMember.organization_id == Conversation.organization_id)).where(Conversation.id == conversation_id, Conversation.organization_id == organization_id, ConversationMember.user_id == user_id, ConversationMember.member_type == "user", ConversationMember.removed_at.is_(None))).scalar_one_or_none()


def list_conversations(db: Session, *, organization_id: str, user_id: str) -> list[Conversation]:
    return db.execute(select(Conversation).join(ConversationMember, (ConversationMember.conversation_id == Conversation.id) & (ConversationMember.organization_id == Conversation.organization_id)).where(Conversation.organization_id == organization_id, ConversationMember.user_id == user_id, ConversationMember.member_type == "user", ConversationMember.removed_at.is_(None)).order_by(Conversation.updated_at.desc())).scalars().all()


def append_user_message(db: Session, *, organization_id: str, conversation_id: str, user_id: str, content: str, idempotency_key: str, expected_state_version: int) -> ConversationMessage:
    conversation = get_conversation(db, organization_id=organization_id, conversation_id=conversation_id, user_id=user_id)
    if conversation is None:
        raise ConversationNotFoundError("Conversation not found.")
    fingerprint = sha256(content.encode("utf-8")).hexdigest()
    existing = db.execute(select(ConversationMessage).where(ConversationMessage.organization_id == organization_id, ConversationMessage.conversation_id == conversation_id, ConversationMessage.idempotency_key == idempotency_key)).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ConversationConflictError("Idempotency key was already used with different content.")
        return existing
    if conversation.state_version != expected_state_version:
        raise ConversationConflictError(f"Conversation state version conflict; current version is {conversation.state_version}.")
    if conversation.status not in {"active", "completed", "failed", "cancelled"}:
        raise ConversationValidationError("Conversation is not accepting a new user message.")
    locked = db.execute(select(Conversation).where(Conversation.id == conversation_id, Conversation.organization_id == organization_id).with_for_update()).scalar_one()
    if locked.state_version != expected_state_version:
        raise ConversationConflictError(f"Conversation state version conflict; current version is {locked.state_version}.")
    next_sequence = (db.execute(select(func.max(ConversationMessage.sequence_number)).where(ConversationMessage.organization_id == organization_id, ConversationMessage.conversation_id == conversation_id)).scalar() or 0) + 1
    redacted, classification = _redact_and_classify(content)
    correlation_id = str(uuid4())
    row = ConversationMessage(id=str(uuid4()), organization_id=organization_id, conversation_id=conversation_id, sequence_number=next_sequence, sender_type="user", sender_user_id=user_id, message_type="user_message", content_ciphertext=_fernet().encrypt(content.encode("utf-8")).decode("utf-8"), content_redacted=redacted, data_classification=classification, encryption_key_ref="settings:conversation_encryption_key", idempotency_key=idempotency_key, request_fingerprint=fingerprint, correlation_id=correlation_id)
    locked.status = "active"
    locked.state_version += 1
    db.add(row)
    _audit(db, organization_id=organization_id, conversation_id=conversation_id, action="conversation.message_created", actor_id=user_id, correlation_id=correlation_id, metadata=f"classification={classification};sequence={next_sequence}")
    enqueue_message_event(db, organization_id=organization_id, conversation_id=conversation_id, message_id=row.id, sequence_number=next_sequence, classification=classification, correlation_id=correlation_id, idempotency_key=idempotency_key)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConversationConflictError("Concurrent message submission conflict.") from exc
    db.refresh(row)
    return row


def list_messages(db: Session, *, organization_id: str, conversation_id: str, user_id: str) -> list[ConversationMessage]:
    if get_conversation(db, organization_id=organization_id, conversation_id=conversation_id, user_id=user_id) is None:
        raise ConversationNotFoundError("Conversation not found.")
    return db.execute(select(ConversationMessage).where(ConversationMessage.organization_id == organization_id, ConversationMessage.conversation_id == conversation_id).order_by(ConversationMessage.sequence_number.asc())).scalars().all()
