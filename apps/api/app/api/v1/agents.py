from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session, require_permission
from app.core.rbac import AccessContext
from app.models import AgentProfile
from app.schemas.agent import AgentCreateRequest, AgentResponse, AgentUpdateRequest
from app.services.agent_registry import (
    AgentRegistryConflictError,
    AgentRegistryValidationError,
    create_agent_profile,
    get_agent_profile_by_id,
    list_agent_profiles,
    update_agent_profile,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def _to_response(profile: AgentProfile) -> AgentResponse:
    return AgentResponse(
        id=profile.id,
        organization_id=profile.organization_id,
        name=profile.name,
        slug=profile.slug,
        model_provider=profile.model_provider,
        model_name=profile.model_name,
        status=profile.status,
        description=profile.description,
        role=profile.role,
        system_prompt=profile.system_prompt,
        created_by_user_id=profile.created_by_user_id,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: AgentCreateRequest,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.write")),
) -> AgentResponse:
    profile = AgentProfile(
        id=str(uuid4()),
        organization_id=access_context.organization_id,
        name=payload.name.strip(),
        slug=payload.slug.strip().lower(),
        model_provider=payload.model_provider.strip(),
        model_name=payload.model_name.strip(),
        description=payload.description.strip() if payload.description is not None else None,
        role=payload.role.strip() if payload.role is not None else None,
        system_prompt=payload.system_prompt.strip() if payload.system_prompt is not None else None,
        status=payload.status,
        created_by_user_id=access_context.user_id,
    )
    try:
        created = create_agent_profile(db, profile=profile)
    except AgentRegistryConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_response(created)


@router.get("", response_model=list[AgentResponse])
def list_agents(
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.read")),
) -> list[AgentResponse]:
    rows = list_agent_profiles(db, organization_id=access_context.organization_id)
    return [_to_response(row) for row in rows]


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(
    agent_id: UUID,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.read")),
) -> AgentResponse:
    row = get_agent_profile_by_id(
        db,
        organization_id=access_context.organization_id,
        agent_id=str(agent_id),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return _to_response(row)


@router.patch("/{agent_id}", response_model=AgentResponse)
def patch_agent(
    agent_id: UUID,
    payload: AgentUpdateRequest,
    db: Session = Depends(get_db_session),
    access_context: AccessContext = Depends(require_permission("agent.write")),
) -> AgentResponse:
    if hasattr(payload, "model_dump"):
        changes = payload.model_dump(exclude_unset=True)
    else:
        changes = payload.dict(exclude_unset=True)
    if "slug" in changes and changes["slug"] is not None:
        changes["slug"] = changes["slug"].strip().lower()

    try:
        row = update_agent_profile(
            db,
            organization_id=access_context.organization_id,
            agent_id=str(agent_id),
            changes=changes,
        )
    except AgentRegistryConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AgentRegistryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return _to_response(row)
