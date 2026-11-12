from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session, require_permission
from app.core.rbac import AccessContext
from app.schemas.agent_runtime import (
    AgentExecutionApprovalResponse,
    AgentExecutionAuditResponse,
    AgentExecutionResponse,
    AgentExecutionTaskResponse,
    AgentVersionResponse,
    ExecutionMetricsResponse,
    PublishAgentVersionRequest,
    QueueTaskRequest,
    RequestApprovalPayload,
    RetryExecutionRequest,
    ReviewApprovalPayload,
    StartExecutionRequest,
    UpdateExecutionStatusRequest,
)
from app.services.agent_runtime_engine import (
    RuntimeConflictError,
    RuntimeNotFoundError,
    RuntimeValidationError,
    expire_pending_approvals,
    get_execution,
    get_next_ready_task,
    list_agent_versions,
    list_execution_audit_logs,
    publish_agent_version,
    queue_execution_task,
    request_execution_approval,
    retry_execution,
    review_execution_approval,
    start_execution,
    update_execution_status,
)

router = APIRouter(prefix="/agent-runtime", tags=["agent-runtime"])


def _to_agent_version_response(row) -> AgentVersionResponse:
    return AgentVersionResponse(
        id=row.id,
        organization_id=row.organization_id,
        agent_profile_id=row.agent_profile_id,
        version_number=row.version_number,
        is_published=row.is_published,
        snapshot_name=row.snapshot_name,
        snapshot_role=row.snapshot_role,
        snapshot_model_provider=row.snapshot_model_provider,
        snapshot_model_name=row.snapshot_model_name,
        snapshot_system_prompt=row.snapshot_system_prompt,
        published_by_user_id=row.published_by_user_id,
        published_at=row.published_at.isoformat(),
    )


def _to_execution_response(row) -> AgentExecutionResponse:
    return AgentExecutionResponse(
        id=row.id,
        organization_id=row.organization_id,
        agent_profile_id=row.agent_profile_id,
        agent_version_id=row.agent_version_id,
        requested_by_user_id=row.requested_by_user_id,
        project_id=row.project_id,
        status=row.status,
        idempotency_key=row.idempotency_key,
        timeout_seconds=row.timeout_seconds,
        max_retries=row.max_retries,
        retry_count=row.retry_count,
        next_retry_at=row.next_retry_at.isoformat() if row.next_retry_at else None,
        token_input_count=row.token_input_count,
        token_output_count=row.token_output_count,
        duration_ms=row.duration_ms,
        last_error_code=row.last_error_code,
        last_error_message=row.last_error_message,
        input_payload=row.input_payload,
        result_payload=row.result_payload,
        failure_reason=row.failure_reason,
        created_at=row.created_at.isoformat(),
        started_at=row.started_at.isoformat() if row.started_at else None,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
    )


def _to_task_response(row) -> AgentExecutionTaskResponse:
    return AgentExecutionTaskResponse(
        id=row.id,
        organization_id=row.organization_id,
        execution_id=row.execution_id,
        queue_position=row.queue_position,
        task_type=row.task_type,
        depends_on_task_id=row.depends_on_task_id,
        scheduled_at=row.scheduled_at.isoformat() if row.scheduled_at else None,
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        last_error_code=row.last_error_code,
        last_error_message=row.last_error_message,
        task_payload=row.task_payload,
        status=row.status,
        created_at=row.created_at.isoformat(),
        started_at=row.started_at.isoformat() if row.started_at else None,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
    )


def _to_approval_response(row) -> AgentExecutionApprovalResponse:
    return AgentExecutionApprovalResponse(
        id=row.id,
        organization_id=row.organization_id,
        execution_id=row.execution_id,
        requested_by_user_id=row.requested_by_user_id,
        reviewer_user_id=row.reviewer_user_id,
        status=row.status,
        request_reason=row.request_reason,
        review_comment=row.review_comment,
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        requested_at=row.requested_at.isoformat(),
        reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
        expired_at=row.expired_at.isoformat() if row.expired_at else None,
    )


def _to_audit_response(row) -> AgentExecutionAuditResponse:
    return AgentExecutionAuditResponse(
        id=row.id,
        organization_id=row.organization_id,
        execution_id=row.execution_id,
        action=row.action,
        actor_user_id=row.actor_user_id,
        details=row.details,
        created_at=row.created_at.isoformat(),
    )


def _parse_scheduled_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid scheduled_at format.") from exc


@router.post("/agents/{agent_id}/versions/publish", response_model=AgentVersionResponse, status_code=status.HTTP_201_CREATED)
def publish_version(
    agent_id: UUID,
    _payload: PublishAgentVersionRequest,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.write")),
) -> AgentVersionResponse:
    try:
        row = publish_agent_version(
            db,
            organization_id=access_context.organization_id,
            agent_id=str(agent_id),
            actor_user_id=access_context.user_id,
        )
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_agent_version_response(row)


@router.get("/agents/{agent_id}/versions", response_model=list[AgentVersionResponse])
def get_versions(
    agent_id: UUID,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.runtime.read")),
) -> list[AgentVersionResponse]:
    rows = list_agent_versions(
        db,
        organization_id=access_context.organization_id,
        agent_id=str(agent_id),
    )
    return [_to_agent_version_response(row) for row in rows]


@router.post("/agents/{agent_id}/executions", response_model=AgentExecutionResponse, status_code=status.HTTP_201_CREATED)
def create_execution(
    agent_id: UUID,
    payload: StartExecutionRequest,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.execute")),
) -> AgentExecutionResponse:
    try:
        row = start_execution(
            db,
            organization_id=access_context.organization_id,
            agent_id=str(agent_id),
            requested_by_user_id=access_context.user_id,
            project_id=payload.project_id,
            input_payload=payload.input_payload,
            initial_task_type=payload.initial_task_type,
            initial_task_payload=payload.initial_task_payload,
            idempotency_key=payload.idempotency_key,
            timeout_seconds=payload.timeout_seconds,
            max_retries=payload.max_retries,
        )
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_execution_response(row)


@router.get("/executions/{execution_id}", response_model=AgentExecutionResponse)
def get_execution_by_id(
    execution_id: UUID,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.runtime.read")),
) -> AgentExecutionResponse:
    row = get_execution(
        db,
        organization_id=access_context.organization_id,
        execution_id=str(execution_id),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found.")
    return _to_execution_response(row)


@router.post("/executions/{execution_id}/tasks", response_model=AgentExecutionTaskResponse, status_code=status.HTTP_201_CREATED)
def enqueue_task(
    execution_id: UUID,
    payload: QueueTaskRequest,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.execute")),
) -> AgentExecutionTaskResponse:
    try:
        row = queue_execution_task(
            db,
            organization_id=access_context.organization_id,
            execution_id=str(execution_id),
            task_type=payload.task_type,
            task_payload=payload.task_payload,
            actor_user_id=access_context.user_id,
            depends_on_task_id=payload.depends_on_task_id,
            scheduled_at=_parse_scheduled_at(payload.scheduled_at),
            max_attempts=payload.max_attempts,
        )
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_task_response(row)


@router.get("/executions/{execution_id}/next-task", response_model=AgentExecutionTaskResponse)
def next_ready_task(
    execution_id: UUID,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.execute")),
) -> AgentExecutionTaskResponse:
    try:
        row = get_next_ready_task(
            db,
            organization_id=access_context.organization_id,
            execution_id=str(execution_id),
        )
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No ready task.")
    return _to_task_response(row)


@router.patch("/executions/{execution_id}/status", response_model=AgentExecutionResponse)
def set_execution_status(
    execution_id: UUID,
    payload: UpdateExecutionStatusRequest,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.execute")),
) -> AgentExecutionResponse:
    try:
        row = update_execution_status(
            db,
            organization_id=access_context.organization_id,
            execution_id=str(execution_id),
            status=payload.status,
            actor_user_id=access_context.user_id,
            result_payload=payload.result_payload,
            failure_reason=payload.failure_reason,
            error_code=payload.error_code,
            token_input_count=payload.token_input_count,
            token_output_count=payload.token_output_count,
        )
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_execution_response(row)


@router.post("/executions/{execution_id}/retry", response_model=AgentExecutionResponse)
def retry_failed_execution(
    execution_id: UUID,
    payload: RetryExecutionRequest,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.execute")),
) -> AgentExecutionResponse:
    try:
        row = retry_execution(
            db,
            organization_id=access_context.organization_id,
            execution_id=str(execution_id),
            actor_user_id=access_context.user_id,
            reason=payload.reason,
        )
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_execution_response(row)


@router.post("/executions/{execution_id}/approvals", response_model=AgentExecutionApprovalResponse, status_code=status.HTTP_201_CREATED)
def request_approval(
    execution_id: UUID,
    payload: RequestApprovalPayload,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.execute")),
) -> AgentExecutionApprovalResponse:
    try:
        row = request_execution_approval(
            db,
            organization_id=access_context.organization_id,
            execution_id=str(execution_id),
            actor_user_id=access_context.user_id,
            reason=payload.reason,
            expires_in_seconds=payload.expires_in_seconds,
        )
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_approval_response(row)


@router.post("/approvals/expire", status_code=status.HTTP_200_OK)
def expire_approvals(
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.approve")),
) -> dict:
    expired_count = expire_pending_approvals(
        db,
        organization_id=access_context.organization_id,
        actor_user_id=access_context.user_id,
    )
    return {"expired_count": expired_count}


@router.patch("/approvals/{approval_id}", response_model=AgentExecutionApprovalResponse)
def review_approval(
    approval_id: UUID,
    payload: ReviewApprovalPayload,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.approve")),
) -> AgentExecutionApprovalResponse:
    try:
        row = review_execution_approval(
            db,
            organization_id=access_context.organization_id,
            approval_id=str(approval_id),
            reviewer_user_id=access_context.user_id,
            status=payload.status,
            comment=payload.comment,
        )
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_approval_response(row)


@router.get("/executions/{execution_id}/audit-logs", response_model=list[AgentExecutionAuditResponse])
def get_execution_audit_logs(
    execution_id: UUID,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("audit.read")),
) -> list[AgentExecutionAuditResponse]:
    rows = list_execution_audit_logs(
        db,
        organization_id=access_context.organization_id,
        execution_id=str(execution_id),
    )
    return [_to_audit_response(row) for row in rows]


@router.get("/executions/{execution_id}/metrics", response_model=ExecutionMetricsResponse)
def get_execution_metrics(
    execution_id: UUID,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.runtime.read")),
) -> ExecutionMetricsResponse:
    row = get_execution(
        db,
        organization_id=access_context.organization_id,
        execution_id=str(execution_id),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found.")
    return ExecutionMetricsResponse(
        execution_id=row.id,
        status=row.status,
        duration_ms=row.duration_ms,
        retry_count=row.retry_count,
        max_retries=row.max_retries,
        token_input_count=row.token_input_count,
        token_output_count=row.token_output_count,
        last_error_code=row.last_error_code,
    )
