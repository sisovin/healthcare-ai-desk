from datetime import UTC, datetime, timedelta
import re
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AgentExecution,
    AgentExecutionApproval,
    AgentExecutionAuditLog,
    AgentExecutionTask,
    AgentProfile,
    AgentVersion,
    ConversationTask,
)
from app.services.safety_policy import evaluate_execution_safety

TERMINAL_EXECUTION_STATUSES = {"succeeded", "failed", "cancelled"}

EXECUTION_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"queued", "running", "waiting_approval", "cancelled", "failed"},
    "running": {"running", "waiting_approval", "succeeded", "failed", "cancelled"},
    "waiting_approval": {"waiting_approval", "queued", "running", "cancelled", "failed"},
    "succeeded": {"succeeded"},
    "failed": {"failed", "queued"},
    "cancelled": {"cancelled", "queued"},
}

SENSITIVE_PATTERN = re.compile(
    r'(?i)("?(password|secret|token|api[_-]?key|authorization)"?\s*[:=]\s*)"[^"]*"'
)


class RuntimeNotFoundError(Exception):
    pass


class RuntimeValidationError(Exception):
    pass


class RuntimeConflictError(Exception):
    pass


def _redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    return SENSITIVE_PATTERN.sub(r'\1"[REDACTED]"', value)


def _duration_ms(started_at: datetime, ended_at: datetime) -> int:
    if started_at.tzinfo is None and ended_at.tzinfo is not None:
        ended_at = ended_at.replace(tzinfo=None)
    elif started_at.tzinfo is not None and ended_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=None)
    return max(0, int((ended_at - started_at).total_seconds() * 1000))


def _append_audit_log(
    db: Session,
    *,
    organization_id: str,
    execution_id: str,
    action: str,
    actor_user_id: str | None,
    details: str | None = None,
) -> AgentExecutionAuditLog:
    row = AgentExecutionAuditLog(
        id=str(uuid4()),
        organization_id=organization_id,
        execution_id=execution_id,
        action=action,
        actor_user_id=actor_user_id,
        details=_redact_text(details),
    )
    db.add(row)
    return row


def publish_agent_version(
    db: Session,
    *,
    organization_id: str,
    agent_id: str,
    actor_user_id: str,
) -> AgentVersion:
    profile = db.execute(
        select(AgentProfile).where(
            AgentProfile.id == agent_id,
            AgentProfile.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if profile is None:
        raise RuntimeNotFoundError("Agent not found.")

    max_number = db.execute(
        select(func.max(AgentVersion.version_number)).where(
            AgentVersion.organization_id == organization_id,
            AgentVersion.agent_profile_id == agent_id,
        )
    ).scalar()
    next_number = (max_number or 0) + 1

    row = AgentVersion(
        id=str(uuid4()),
        organization_id=organization_id,
        agent_profile_id=agent_id,
        version_number=next_number,
        is_published=True,
        snapshot_name=profile.name,
        snapshot_role=profile.role,
        snapshot_model_provider=profile.model_provider,
        snapshot_model_name=profile.model_name,
        snapshot_system_prompt=profile.system_prompt,
        published_by_user_id=actor_user_id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RuntimeConflictError("Unable to publish agent version due to concurrent update.") from exc
    db.refresh(row)
    return row


def list_agent_versions(
    db: Session,
    *,
    organization_id: str,
    agent_id: str,
) -> list[AgentVersion]:
    return db.execute(
        select(AgentVersion)
        .where(
            AgentVersion.organization_id == organization_id,
            AgentVersion.agent_profile_id == agent_id,
        )
        .order_by(AgentVersion.version_number.desc())
    ).scalars().all()


def _get_latest_published_version(
    db: Session,
    *,
    organization_id: str,
    agent_id: str,
) -> AgentVersion | None:
    return db.execute(
        select(AgentVersion)
        .where(
            AgentVersion.organization_id == organization_id,
            AgentVersion.agent_profile_id == agent_id,
            AgentVersion.is_published.is_(True),
        )
        .order_by(AgentVersion.version_number.desc())
    ).scalars().first()


def start_execution(
    db: Session,
    *,
    organization_id: str,
    agent_id: str,
    requested_by_user_id: str,
    project_id: str | None,
    input_payload: str | None,
    initial_task_type: str,
    initial_task_payload: str | None,
    idempotency_key: str | None,
    timeout_seconds: int,
    max_retries: int,
    commit: bool = True,
) -> AgentExecution:
    profile = db.execute(
        select(AgentProfile).where(
            AgentProfile.id == agent_id,
            AgentProfile.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if profile is None:
        raise RuntimeNotFoundError("Agent not found.")

    if idempotency_key:
        existing = db.execute(
            select(AgentExecution).where(
                AgentExecution.organization_id == organization_id,
                AgentExecution.agent_profile_id == agent_id,
                AgentExecution.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    version = _get_latest_published_version(db, organization_id=organization_id, agent_id=agent_id)
    if version is None:
        raise RuntimeValidationError("No published version found for this agent.")

    try:
        safety = evaluate_execution_safety(
            model_provider=profile.model_provider,
            task_type=initial_task_type,
            input_payload=input_payload,
            task_payload=initial_task_payload,
        )
    except ValueError as exc:
        raise RuntimeValidationError(str(exc)) from exc

    execution = AgentExecution(
        id=str(uuid4()),
        organization_id=organization_id,
        agent_profile_id=agent_id,
        agent_version_id=version.id,
        requested_by_user_id=requested_by_user_id,
        project_id=project_id,
        status="waiting_approval" if safety.requires_human_approval else "queued",
        idempotency_key=idempotency_key,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        input_payload=_redact_text(input_payload),
    )
    db.add(execution)
    db.flush()

    task = AgentExecutionTask(
        id=str(uuid4()),
        organization_id=organization_id,
        execution_id=execution.id,
        queue_position=1,
        task_type=initial_task_type,
        task_payload=_redact_text(initial_task_payload),
        status="pending",
    )
    db.add(task)
    _append_audit_log(
        db,
        organization_id=organization_id,
        execution_id=execution.id,
        action="execution.created",
        actor_user_id=requested_by_user_id,
        details=f"version={version.version_number};idempotency_key={idempotency_key or 'none'}",
    )
    if safety.requires_human_approval:
        _create_policy_approval(
            db,
            organization_id=organization_id,
            execution_id=execution.id,
            actor_user_id=requested_by_user_id,
            reason=safety.reason or "high_impact_action",
        )
    _append_audit_log(
        db,
        organization_id=organization_id,
        execution_id=execution.id,
        action="task.enqueued",
        actor_user_id=requested_by_user_id,
        details=f"task_type={initial_task_type};position=1",
    )

    if commit:
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise RuntimeConflictError("Failed to start execution due to data integrity conflict.") from exc
        db.refresh(execution)
    else:
        db.flush()
    return execution


def _create_policy_approval(
    db: Session,
    *,
    organization_id: str,
    execution_id: str,
    actor_user_id: str,
    reason: str,
) -> AgentExecutionApproval:
    """Create the immutable approval request in the caller's transaction."""
    approval = AgentExecutionApproval(
        id=str(uuid4()),
        organization_id=organization_id,
        execution_id=execution_id,
        requested_by_user_id=actor_user_id,
        status="pending",
        request_reason=reason,
    )
    db.add(approval)
    _append_audit_log(
        db,
        organization_id=organization_id,
        execution_id=execution_id,
        action="approval.required_by_policy",
        actor_user_id=actor_user_id,
        details=f"reason={reason}",
    )
    return approval


def get_execution(
    db: Session,
    *,
    organization_id: str,
    execution_id: str,
) -> AgentExecution | None:
    return db.execute(
        select(AgentExecution).where(
            AgentExecution.id == execution_id,
            AgentExecution.organization_id == organization_id,
        )
    ).scalar_one_or_none()


def _task_dependency_satisfied(db: Session, *, organization_id: str, depends_on_task_id: str | None) -> bool:
    if depends_on_task_id is None:
        return True
    dep = db.execute(
        select(AgentExecutionTask).where(
            AgentExecutionTask.organization_id == organization_id,
            AgentExecutionTask.id == depends_on_task_id,
        )
    ).scalar_one_or_none()
    if dep is None:
        raise RuntimeValidationError("depends_on_task_id not found in organization scope.")
    return dep.status == "succeeded"


def queue_execution_task(
    db: Session,
    *,
    organization_id: str,
    execution_id: str,
    task_type: str,
    task_payload: str | None,
    actor_user_id: str,
    depends_on_task_id: str | None,
    scheduled_at: datetime | None,
    max_attempts: int,
) -> AgentExecutionTask:
    execution = get_execution(db, organization_id=organization_id, execution_id=execution_id)
    if execution is None:
        raise RuntimeNotFoundError("Execution not found.")
    if execution.status in TERMINAL_EXECUTION_STATUSES:
        raise RuntimeValidationError("Cannot queue tasks for terminal execution.")

    profile = db.execute(
        select(AgentProfile).where(
            AgentProfile.id == execution.agent_profile_id,
            AgentProfile.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if profile is None:
        raise RuntimeNotFoundError("Agent not found for execution.")
    try:
        safety = evaluate_execution_safety(
            model_provider=profile.model_provider,
            task_type=task_type,
            input_payload=None,
            task_payload=task_payload,
        )
    except ValueError as exc:
        raise RuntimeValidationError(str(exc)) from exc

    max_position = db.execute(
        select(func.max(AgentExecutionTask.queue_position)).where(
            AgentExecutionTask.organization_id == organization_id,
            AgentExecutionTask.execution_id == execution_id,
        )
    ).scalar()
    next_position = (max_position or 0) + 1

    dependency_ready = _task_dependency_satisfied(db, organization_id=organization_id, depends_on_task_id=depends_on_task_id)
    initial_status = "pending" if dependency_ready else "blocked"

    row = AgentExecutionTask(
        id=str(uuid4()),
        organization_id=organization_id,
        execution_id=execution_id,
        queue_position=next_position,
        task_type=task_type,
        task_payload=_redact_text(task_payload),
        depends_on_task_id=depends_on_task_id,
        scheduled_at=scheduled_at,
        max_attempts=max_attempts,
        status=initial_status,
    )
    db.add(row)
    _append_audit_log(
        db,
        organization_id=organization_id,
        execution_id=execution_id,
        action="task.enqueued",
        actor_user_id=actor_user_id,
        details=f"task_type={task_type};position={next_position};status={initial_status}",
    )
    if safety.requires_human_approval:
        execution.status = "waiting_approval"
        _create_policy_approval(
            db,
            organization_id=organization_id,
            execution_id=execution.id,
            actor_user_id=actor_user_id,
            reason=safety.reason or "high_impact_action",
        )
        db.add(execution)
    db.commit()
    db.refresh(row)
    return row


def get_next_ready_task(
    db: Session,
    *,
    organization_id: str,
    execution_id: str,
) -> AgentExecutionTask | None:
    execution = get_execution(db, organization_id=organization_id, execution_id=execution_id)
    if execution is None:
        raise RuntimeNotFoundError("Execution not found.")

    now = datetime.now(UTC)
    tasks = db.execute(
        select(AgentExecutionTask)
        .where(
            AgentExecutionTask.organization_id == organization_id,
            AgentExecutionTask.execution_id == execution_id,
            AgentExecutionTask.status.in_(["pending", "blocked"]),
        )
        .order_by(AgentExecutionTask.queue_position.asc())
    ).scalars().all()

    for task in tasks:
        if task.scheduled_at is not None and task.scheduled_at > now:
            continue
        if task.depends_on_task_id and not _task_dependency_satisfied(
            db, organization_id=organization_id, depends_on_task_id=task.depends_on_task_id
        ):
            task.status = "blocked"
            continue
        if task.status == "blocked":
            task.status = "pending"
            db.add(task)
            db.commit()
            db.refresh(task)
        return task
    return None


def update_execution_status(
    db: Session,
    *,
    organization_id: str,
    execution_id: str,
    status: str,
    actor_user_id: str,
    result_payload: str | None = None,
    failure_reason: str | None = None,
    error_code: str | None = None,
    token_input_count: int | None = None,
    token_output_count: int | None = None,
) -> AgentExecution:
    execution = get_execution(db, organization_id=organization_id, execution_id=execution_id)
    if execution is None:
        raise RuntimeNotFoundError("Execution not found.")

    normalized_status = "succeeded" if status == "completed" else status
    allowed = EXECUTION_TRANSITIONS.get(execution.status, {execution.status})
    if normalized_status not in allowed:
        raise RuntimeValidationError(
            f"Invalid execution transition from '{execution.status}' to '{normalized_status}'."
        )
    if normalized_status == "running":
        pending_approval = db.execute(
            select(AgentExecutionApproval.id).where(
                AgentExecutionApproval.organization_id == organization_id,
                AgentExecutionApproval.execution_id == execution_id,
                AgentExecutionApproval.status == "pending",
            )
        ).scalar_one_or_none()
        if pending_approval is not None:
            raise RuntimeValidationError("Execution cannot run while a human approval request is pending.")

    now = datetime.now(UTC)
    execution.status = normalized_status
    if normalized_status == "running" and execution.started_at is None:
        execution.started_at = now
    if normalized_status in TERMINAL_EXECUTION_STATUSES:
        execution.completed_at = now
        if execution.started_at is not None:
            execution.duration_ms = _duration_ms(execution.started_at, now)
    if result_payload is not None:
        execution.result_payload = _redact_text(result_payload)
    if failure_reason is not None:
        execution.failure_reason = _redact_text(failure_reason)
    if error_code is not None:
        execution.last_error_code = error_code
    if token_input_count is not None:
        execution.token_input_count = token_input_count
    if token_output_count is not None:
        execution.token_output_count = token_output_count
    execution.last_error_message = _redact_text(failure_reason) if failure_reason else execution.last_error_message

    if normalized_status == "failed" and execution.retry_count < execution.max_retries:
        execution.next_retry_at = now + timedelta(seconds=30)
    else:
        execution.next_retry_at = None

    _append_audit_log(
        db,
        organization_id=organization_id,
        execution_id=execution_id,
        action="execution.status_updated",
        actor_user_id=actor_user_id,
        details=f"status={normalized_status};error_code={error_code or 'none'}",
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def retry_execution(
    db: Session,
    *,
    organization_id: str,
    execution_id: str,
    actor_user_id: str,
    reason: str | None,
) -> AgentExecution:
    execution = get_execution(db, organization_id=organization_id, execution_id=execution_id)
    if execution is None:
        raise RuntimeNotFoundError("Execution not found.")
    if execution.status not in {"failed", "cancelled"}:
        raise RuntimeValidationError("Retry is allowed only for failed or cancelled executions.")
    if execution.retry_count >= execution.max_retries:
        raise RuntimeValidationError("Retry limit exceeded.")

    execution.retry_count += 1
    execution.status = "queued"
    execution.next_retry_at = None
    execution.completed_at = None
    execution.failure_reason = None
    execution.last_error_message = None
    _append_audit_log(
        db,
        organization_id=organization_id,
        execution_id=execution_id,
        action="execution.retried",
        actor_user_id=actor_user_id,
        details=_redact_text(reason),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def request_execution_approval(
    db: Session,
    *,
    organization_id: str,
    execution_id: str,
    actor_user_id: str,
    reason: str | None,
    expires_in_seconds: int | None,
) -> AgentExecutionApproval:
    execution = get_execution(db, organization_id=organization_id, execution_id=execution_id)
    if execution is None:
        raise RuntimeNotFoundError("Execution not found.")
    execution.status = "waiting_approval"

    expires_at = None
    if expires_in_seconds is not None:
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)

    approval = AgentExecutionApproval(
        id=str(uuid4()),
        organization_id=organization_id,
        execution_id=execution_id,
        requested_by_user_id=actor_user_id,
        status="pending",
        request_reason=_redact_text(reason),
        expires_at=expires_at,
    )
    db.add(approval)
    _append_audit_log(
        db,
        organization_id=organization_id,
        execution_id=execution_id,
        action="approval.requested",
        actor_user_id=actor_user_id,
        details=f"expires_at={expires_at.isoformat() if expires_at else 'none'}",
    )
    db.commit()
    db.refresh(approval)
    return approval


def expire_pending_approvals(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: str | None,
) -> int:
    now = datetime.now(UTC)
    pending = db.execute(
        select(AgentExecutionApproval).where(
            AgentExecutionApproval.organization_id == organization_id,
            AgentExecutionApproval.status == "pending",
            AgentExecutionApproval.expires_at.is_not(None),
            AgentExecutionApproval.expires_at <= now,
        )
    ).scalars().all()

    expired_count = 0
    for approval in pending:
        execution = get_execution(db, organization_id=organization_id, execution_id=approval.execution_id)
        if execution is None:
            continue
        approval.status = "expired"
        approval.expired_at = now
        execution.status = "cancelled"
        execution.completed_at = now
        execution.failure_reason = "approval_expired"
        db.add(approval)
        db.add(execution)
        _append_audit_log(
            db,
            organization_id=organization_id,
            execution_id=execution.id,
            action="approval.expired",
            actor_user_id=actor_user_id,
            details="expired_by_scheduler",
        )
        expired_count += 1

    if expired_count:
        db.commit()
    return expired_count


def review_execution_approval(
    db: Session,
    *,
    organization_id: str,
    approval_id: str,
    reviewer_user_id: str,
    status: str,
    comment: str | None,
) -> AgentExecutionApproval:
    approval = db.execute(
        select(AgentExecutionApproval).where(
            AgentExecutionApproval.id == approval_id,
            AgentExecutionApproval.organization_id == organization_id,
        ).with_for_update()
    ).scalar_one_or_none()
    if approval is None:
        raise RuntimeNotFoundError("Approval request not found.")
    if approval.status != "pending":
        raise RuntimeValidationError("Approval request is already finalized.")

    if approval.expires_at is not None and approval.expires_at <= datetime.now(UTC):
        raise RuntimeValidationError("Approval request has expired.")

    execution = get_execution(db, organization_id=organization_id, execution_id=approval.execution_id)
    if execution is None:
        raise RuntimeNotFoundError("Execution not found.")
    if approval.requested_by_user_id == reviewer_user_id:
        raise RuntimeValidationError("The requester cannot approve or reject their own approval request.")

    approval.status = status
    approval.reviewer_user_id = reviewer_user_id
    approval.review_comment = _redact_text(comment)
    approval.reviewed_at = datetime.now(UTC)
    execution.status = "queued" if status == "approved" else "cancelled"
    if status == "rejected":
        execution.completed_at = datetime.now(UTC)
        execution.failure_reason = _redact_text(comment) or "approval_rejected"

    # The Supervisor owns the conversation-task projection, but its state must
    # remain transactionally aligned with the sole M2.5 approval decision.
    for conversation_task in db.execute(
        select(ConversationTask).where(
            ConversationTask.organization_id == organization_id,
            ConversationTask.execution_id == execution.id,
            ConversationTask.status == "waiting_approval",
        )
    ).scalars():
        conversation_task.status = "queued" if status == "approved" else "cancelled"
        db.add(conversation_task)

    _append_audit_log(
        db,
        organization_id=organization_id,
        execution_id=execution.id,
        action="approval.reviewed",
        actor_user_id=reviewer_user_id,
        details=f"status={status}",
    )

    db.add(approval)
    db.add(execution)
    db.commit()
    db.refresh(approval)
    return approval


def list_execution_audit_logs(
    db: Session,
    *,
    organization_id: str,
    execution_id: str,
) -> list[AgentExecutionAuditLog]:
    return db.execute(
        select(AgentExecutionAuditLog)
        .where(
            AgentExecutionAuditLog.organization_id == organization_id,
            AgentExecutionAuditLog.execution_id == execution_id,
        )
        .order_by(AgentExecutionAuditLog.created_at.asc())
    ).scalars().all()
