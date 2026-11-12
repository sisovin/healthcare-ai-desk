from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session, require_permission
from app.core.rbac import AccessContext
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageCreateRequest, ConversationMessageResponse, ConversationResponse
from app.services.conversation_service import ConversationConflictError, ConversationNotFoundError, ConversationValidationError, append_user_message, create_conversation, get_conversation, list_conversations, list_messages
from app.services.outbox_service import backlog_metrics, replay_failed_event
from app.schemas.supervisor import SupervisorPlanCreateRequest
from app.services.supervisor_service import PlanValidationError, create_plan

router = APIRouter(prefix="/conversations", tags=["conversations"])

def _conversation(row) -> ConversationResponse:
    return ConversationResponse(id=row.id, organization_id=row.organization_id, project_id=row.project_id, title=row.title, status=row.status, state_version=row.state_version, created_by_user_id=row.created_by_user_id, created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat())

def _message(row) -> ConversationMessageResponse:
    return ConversationMessageResponse(id=row.id, conversation_id=row.conversation_id, sequence_number=row.sequence_number, sender_type=row.sender_type, message_type=row.message_type, content=row.content_redacted, data_classification=row.data_classification, correlation_id=row.correlation_id, created_at=row.created_at.isoformat())

@router.post("/{conversation_id}/plans", status_code=status.HTTP_201_CREATED)
def create_supervisor_plan(conversation_id: UUID, payload: SupervisorPlanCreateRequest, db: Session = Depends(get_db_session), access: AccessContext = Depends(require_permission("conversation.manage"))) -> dict:
    try:
        row = create_plan(db, organization_id=access.organization_id, conversation_id=str(conversation_id), actor_user_id=access.user_id, goal=payload.goal, strategy=payload.strategy, tasks=[task.model_dump() for task in payload.tasks])
        return {"id": row.id, "plan_version": row.plan_version, "status": row.status}
    except ConversationNotFoundError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlanValidationError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/outbox/health")
def outbox_health(db: Session = Depends(get_db_session), access: AccessContext = Depends(require_permission("conversation.audit.read"))) -> dict[str, int]:
    return backlog_metrics(db, organization_id=access.organization_id)

@router.post("/outbox/events/{event_id}/replay")
def replay_outbox_event(event_id: UUID, db: Session = Depends(get_db_session), access: AccessContext = Depends(require_permission("conversation.manage"))) -> dict[str, str]:
    row = replay_failed_event(db, organization_id=access.organization_id, event_id=str(event_id), actor_user_id=access.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Failed outbox event not found.")
    return {"id": row.id, "status": row.status}

@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create(payload: ConversationCreateRequest, db: Session = Depends(get_db_session), access: AccessContext = Depends(require_permission("conversation.write"))) -> ConversationResponse:
    try:
        return _conversation(create_conversation(db, organization_id=access.organization_id, project_id=payload.project_id, title=payload.title, actor_user_id=access.user_id))
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("", response_model=list[ConversationResponse])
def list_all(db: Session = Depends(get_db_session), access: AccessContext = Depends(require_permission("conversation.read"))) -> list[ConversationResponse]:
    return [_conversation(row) for row in list_conversations(db, organization_id=access.organization_id, user_id=access.user_id)]

@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_one(conversation_id: UUID, db: Session = Depends(get_db_session), access: AccessContext = Depends(require_permission("conversation.read"))) -> ConversationResponse:
    row = get_conversation(db, organization_id=access.organization_id, conversation_id=str(conversation_id), user_id=access.user_id)
    if row is None: raise HTTPException(status_code=404, detail="Conversation not found.")
    return _conversation(row)

@router.post("/{conversation_id}/messages", response_model=ConversationMessageResponse, status_code=status.HTTP_201_CREATED)
def post_message(conversation_id: UUID, payload: ConversationMessageCreateRequest, db: Session = Depends(get_db_session), access: AccessContext = Depends(require_permission("conversation.write"))) -> ConversationMessageResponse:
    try:
        return _message(append_user_message(db, organization_id=access.organization_id, conversation_id=str(conversation_id), user_id=access.user_id, content=payload.content, idempotency_key=payload.idempotency_key, expected_state_version=payload.expected_state_version))
    except ConversationNotFoundError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConversationConflictError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ConversationValidationError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/{conversation_id}/messages", response_model=list[ConversationMessageResponse])
def get_messages(conversation_id: UUID, db: Session = Depends(get_db_session), access: AccessContext = Depends(require_permission("conversation.read"))) -> list[ConversationMessageResponse]:
    try: return [_message(row) for row in list_messages(db, organization_id=access.organization_id, conversation_id=str(conversation_id), user_id=access.user_id)]
    except ConversationNotFoundError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
