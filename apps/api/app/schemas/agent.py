from pydantic import BaseModel, Field


AGENT_STATUSES = ("draft", "active", "disabled", "archived")


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=80)
    model_provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    role: str | None = Field(default=None, max_length=80)
    system_prompt: str | None = Field(default=None, max_length=10000)
    status: str = Field(default="draft", pattern="^(draft|active|disabled|archived)$")


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=80)
    model_provider: str | None = Field(default=None, min_length=1, max_length=64)
    model_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    role: str | None = Field(default=None, max_length=80)
    system_prompt: str | None = Field(default=None, max_length=10000)
    status: str | None = Field(default=None, pattern="^(draft|active|disabled|archived)$")


class AgentResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    slug: str
    model_provider: str
    model_name: str
    status: str
    description: str | None
    role: str | None
    system_prompt: str | None
    created_by_user_id: str | None
    created_at: str
    updated_at: str
