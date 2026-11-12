from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AgentProfile

ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"draft", "active", "disabled", "archived"},
    "active": {"active", "disabled", "archived"},
    "disabled": {"disabled", "active", "archived"},
    "archived": {"archived"},
}


class AgentRegistryConflictError(Exception):
    pass


class AgentRegistryValidationError(Exception):
    pass


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized if normalized else None


def create_agent_profile(
    db: Session,
    *,
    profile: AgentProfile,
) -> AgentProfile:
    db.add(profile)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AgentRegistryConflictError("Agent slug already exists in this organization.") from exc
    db.refresh(profile)
    return profile


def list_agent_profiles(
    db: Session,
    *,
    organization_id: str,
) -> Sequence[AgentProfile]:
    return db.execute(
        select(AgentProfile)
        .where(AgentProfile.organization_id == organization_id)
        .order_by(AgentProfile.created_at.desc())
    ).scalars().all()


def get_agent_profile_by_id(
    db: Session,
    *,
    organization_id: str,
    agent_id: str,
) -> AgentProfile | None:
    return db.execute(
        select(AgentProfile).where(
            AgentProfile.id == agent_id,
            AgentProfile.organization_id == organization_id,
        )
    ).scalar_one_or_none()


def update_agent_profile(
    db: Session,
    *,
    organization_id: str,
    agent_id: str,
    changes: dict,
) -> AgentProfile | None:
    profile = get_agent_profile_by_id(db, organization_id=organization_id, agent_id=agent_id)
    if profile is None:
        return None
    if not changes:
        raise AgentRegistryValidationError("No update fields provided.")

    next_status = changes.get("status")
    if next_status is not None:
        allowed = ALLOWED_STATUS_TRANSITIONS.get(profile.status, {profile.status})
        if next_status not in allowed:
            raise AgentRegistryValidationError(
                f"Invalid status transition from '{profile.status}' to '{next_status}'."
            )

    for key, value in changes.items():
        if key in {"name", "slug", "model_provider", "model_name"} and isinstance(value, str):
            setattr(profile, key, value.strip())
        elif key in {"description", "role", "system_prompt"}:
            setattr(profile, key, _normalize_optional(value))
        else:
            setattr(profile, key, value)

    try:
        db.add(profile)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AgentRegistryConflictError("Agent slug already exists in this organization.") from exc

    db.refresh(profile)
    return profile
