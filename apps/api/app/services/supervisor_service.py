import json
from uuid import uuid4
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import AgentProfile, AgentProjectAssignment, ConversationTask, ConversationTaskDependency, SupervisorPlan
from app.services.agent_runtime_engine import start_execution
from app.services.conversation_service import ConversationNotFoundError, get_conversation

class PlanValidationError(Exception): pass


def _after_supervisor_records_flushed(db: Session, *, plan: SupervisorPlan, tasks: dict[str, ConversationTask]) -> None:
    """Extension point for observability; production intentionally performs no action.

    The surrounding transaction remains owned by ``create_plan``.  Fault-injection
    tests patch this boundary only to prove that a rollback after all supervisor
    records are flushed leaves no durable partial state.
    """

def create_plan(db: Session, *, organization_id: str, conversation_id: str, actor_user_id: str, goal: str, strategy: str, tasks: list[dict]) -> SupervisorPlan:
    try:
        return _create_plan_transaction(db, organization_id=organization_id, conversation_id=conversation_id, actor_user_id=actor_user_id, goal=goal, strategy=strategy, tasks=tasks)
    except Exception:
        db.rollback()
        raise

def _create_plan_transaction(db: Session, *, organization_id: str, conversation_id: str, actor_user_id: str, goal: str, strategy: str, tasks: list[dict]) -> SupervisorPlan:
    conversation = get_conversation(db, organization_id=organization_id, conversation_id=conversation_id, user_id=actor_user_id)
    if conversation is None: raise ConversationNotFoundError("Conversation not found.")
    keys = [task["key"] for task in tasks]
    if len(keys) != len(set(keys)): raise PlanValidationError("Task keys must be unique.")
    by_key = {task["key"]: task for task in tasks}
    for task in tasks:
        if any(dep not in by_key for dep in task["depends_on"]): raise PlanValidationError("Task dependency key not found.")
        profile = db.execute(select(AgentProfile).join(AgentProjectAssignment, (AgentProjectAssignment.agent_profile_id == AgentProfile.id) & (AgentProjectAssignment.organization_id == AgentProfile.organization_id)).where(AgentProfile.id == task["agent_id"], AgentProfile.organization_id == organization_id, AgentProfile.status == "active", AgentProjectAssignment.project_id == conversation.project_id)).scalar_one_or_none()
        if profile is None: raise PlanValidationError("Agent must be active and assigned to the conversation project.")
        if task["required_capabilities"] and (profile.role or "") not in task["required_capabilities"]: raise PlanValidationError("Agent does not meet required capabilities.")
    visiting, visited = set(), set()
    def visit(key: str):
        if key in visiting: raise PlanValidationError("Task dependency cycle detected.")
        if key not in visited:
            visiting.add(key); [visit(dep) for dep in by_key[key]["depends_on"]]; visiting.remove(key); visited.add(key)
    [visit(key) for key in keys]
    version = (db.execute(select(func.max(SupervisorPlan.plan_version)).where(SupervisorPlan.organization_id == organization_id, SupervisorPlan.conversation_id == conversation_id)).scalar() or 0) + 1
    plan = SupervisorPlan(id=str(uuid4()), organization_id=organization_id, conversation_id=conversation_id, plan_version=version, plan_json=json.dumps({"goal": goal, "strategy": strategy, "tasks": tasks}), created_by_user_id=actor_user_id)
    db.add(plan); db.flush()
    rows = {}
    for task in tasks:
        execution = start_execution(db, organization_id=organization_id, agent_id=task["agent_id"], requested_by_user_id=actor_user_id, project_id=conversation.project_id, input_payload=None, initial_task_type=task["task_type"], initial_task_payload=None, idempotency_key=f"plan:{plan.id}:{task['key']}", timeout_seconds=900, max_retries=2, commit=False)
        row = ConversationTask(id=str(uuid4()), organization_id=organization_id, conversation_id=conversation_id, task_key=task["key"], agent_profile_id=task["agent_id"], agent_version_id=execution.agent_version_id, execution_id=execution.id, task_type=task["task_type"], status="waiting_approval" if execution.status == "waiting_approval" else "queued", is_high_impact=execution.status == "waiting_approval", idempotency_key=f"plan:{plan.id}:{task['key']}")
        db.add(row); rows[task["key"]] = row
    db.flush()
    _after_supervisor_records_flushed(db, plan=plan, tasks=rows)
    for task in tasks:
        for dep in task["depends_on"]: db.add(ConversationTaskDependency(id=str(uuid4()), organization_id=organization_id, conversation_id=conversation_id, task_id=rows[task["key"]].id, depends_on_task_id=rows[dep].id))
    db.commit(); db.refresh(plan); return plan
