from pydantic import BaseModel, Field


class ConversationCreateRequest(BaseModel):
    project_id: str = Field(min_length=36, max_length=36)
    title: str = Field(min_length=1, max_length=200)


class ConversationResponse(BaseModel):
    id: str
    organization_id: str
    project_id: str
    title: str
    status: str
    state_version: int
    created_by_user_id: str
    created_at: str
    updated_at: str


class ConversationMessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    expected_state_version: int = Field(ge=1)


class ConversationMessageResponse(BaseModel):
    id: str
    conversation_id: str
    sequence_number: int
    sender_type: str
    message_type: str
    content: str
    data_classification: str
    correlation_id: str
    created_at: str
