from pydantic import BaseModel, Field

class PlanTask(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    agent_id: str = Field(min_length=36, max_length=36)
    task_type: str = Field(min_length=1, max_length=64)
    depends_on: list[str] = Field(default_factory=list, max_length=12)
    required_capabilities: list[str] = Field(default_factory=list, max_length=8)

class SupervisorPlanCreateRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    strategy: str = Field(pattern="^(sequential|parallel|delegated)$")
    tasks: list[PlanTask] = Field(min_length=1, max_length=12)
