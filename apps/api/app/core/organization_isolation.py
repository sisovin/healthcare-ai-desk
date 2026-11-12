from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.models import Organization

ORGANIZATION_HEADER = "X-Organization-Id"


@dataclass(frozen=True)
class OrganizationContext:
    organization_id: str


def _validate_organization_id(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {ORGANIZATION_HEADER} format.",
        ) from exc
    return str(parsed)


def get_organization_id_from_header(request: Request) -> str:
    header_value = request.headers.get(ORGANIZATION_HEADER)
    if not header_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required header: {ORGANIZATION_HEADER}.",
        )
    return _validate_organization_id(header_value)


def get_organization_context_from_request(request: Request, db: Session) -> OrganizationContext:
    organization_id = get_organization_id_from_header(request)
    organization = db.get(Organization, organization_id)
    if organization is None or not organization.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found or inactive.",
        )
    return OrganizationContext(organization_id=organization_id)


def enforce_organization_scope(resource_organization_id: str, context: OrganizationContext) -> None:
    if resource_organization_id != context.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-organization access is forbidden.",
        )
