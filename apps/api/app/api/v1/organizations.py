from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.dependencies import get_organization_context, require_permission
from app.core.rbac import AccessContext
from app.core.organization_isolation import OrganizationContext, enforce_organization_scope

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/{organization_id}/scope")
def organization_scope_check(
    organization_id: UUID,
    context: OrganizationContext = Depends(get_organization_context),
) -> dict:
    enforce_organization_scope(str(organization_id), context)
    return {
        "organization_id": context.organization_id,
        "isolation": "enforced",
    }


@router.get("/{organization_id}/guarded")
def organization_guarded_access(
    organization_id: UUID,
    access_context: AccessContext = Depends(require_permission("organization.read")),
) -> dict:
    enforce_organization_scope(str(organization_id), OrganizationContext(access_context.organization_id))
    return {
        "organization_id": access_context.organization_id,
        "role": access_context.role,
        "permission": "organization.read",
    }
