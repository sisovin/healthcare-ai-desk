from pydantic import BaseModel, Field


class AgentVersionResponse(BaseModel):
    id: str
    organization_id: str
    agent_profile_id: str
    version_number: int
    is_published: bool
    snapshot_name: str
    snapshot_role: str | None
    snapshot_model_provider: str
    snapshot_model_name: str
    snapshot_system_prompt: str | None
    published_by_user_id: str | None
    published_at: str


class PublishAgentVersionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class StartExecutionRequest(BaseModel):
    project_id: str | None = Field(default=None, min_length=36, max_length=36)
    input_payload: str | None = Field(default=None, max_length=20000)
    initial_task_type: str = Field(default="default", min_length=1, max_length=64)
    initial_task_payload: str | None = Field(default=None, max_length=20000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    timeout_seconds: int = Field(default=900, ge=1, le=86400)
    max_retries: int = Field(default=2, ge=0, le=20)


class QueueTaskRequest(BaseModel):
    task_type: str = Field(min_length=1, max_length=64)
    task_payload: str | None = Field(default=None, max_length=20000)
    depends_on_task_id: str | None = Field(default=None, min_length=36, max_length=36)
    scheduled_at: str | None = Field(default=None, max_length=64)
    max_attempts: int = Field(default=3, ge=1, le=20)


class UpdateExecutionStatusRequest(BaseModel):
    status: str = Field(pattern="^(queued|running|waiting_approval|succeeded|failed|cancelled|completed)$")
    result_payload: str | None = Field(default=None, max_length=20000)
    failure_reason: str | None = Field(default=None, max_length=20000)
    error_code: str | None = Field(default=None, max_length=64)
    token_input_count: int | None = Field(default=None, ge=0)
    token_output_count: int | None = Field(default=None, ge=0)


class RetryExecutionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class RequestApprovalPayload(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    expires_in_seconds: int | None = Field(default=None, ge=60, le=604800)


class ReviewApprovalPayload(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    comment: str | None = Field(default=None, max_length=2000)


class AgentExecutionResponse(BaseModel):
    id: str
    organization_id: str
    agent_profile_id: str
    agent_version_id: str
    requested_by_user_id: str | None
    project_id: str | None
    status: str
    idempotency_key: str | None
    timeout_seconds: int
    max_retries: int
    retry_count: int
    next_retry_at: str | None
    token_input_count: int
    token_output_count: int
    duration_ms: int | None
    last_error_code: str | None
    last_error_message: str | None
    input_payload: str | None
    result_payload: str | None
    failure_reason: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None


class AgentExecutionTaskResponse(BaseModel):
    id: str
    organization_id: str
    execution_id: str
    queue_position: int
    task_type: str
    depends_on_task_id: str | None
    scheduled_at: str | None
    attempt_count: int
    max_attempts: int
    last_error_code: str | None
    last_error_message: str | None
    task_payload: str | None
    status: str
    created_at: str
    started_at: str | None
    completed_at: str | None


class AgentExecutionAuditResponse(BaseModel):
    id: str
    organization_id: str
    execution_id: str
    action: str
    actor_user_id: str | None
    details: str | None
    created_at: str


class AgentExecutionApprovalResponse(BaseModel):
    id: str
    organization_id: str
    execution_id: str
    requested_by_user_id: str | None
    reviewer_user_id: str | None
    status: str
    request_reason: str | None
    review_comment: str | None
    expires_at: str | None
    requested_at: str
    reviewed_at: str | None
    expired_at: str | None


class ExecutionMetricsResponse(BaseModel):
    execution_id: str
    status: str
    duration_ms: int | None
    retry_count: int
    max_retries: int
    token_input_count: int
    token_output_count: int
    last_error_code: str | None
