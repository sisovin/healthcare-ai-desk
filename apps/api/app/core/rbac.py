from dataclasses import dataclass


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": {
        "organization.read",
        "organization.manage_members",
        "project.read",
        "project.write",
        "project.manage_members",
        "audit.read",
    },
    "admin": {
        "organization.read",
        "organization.manage_members",
        "project.read",
        "project.write",
        "project.manage_members",
        "audit.read",
    },
    "manager": {
        "organization.read",
        "project.read",
        "project.write",
        "project.manage_members",
    },
    "member": {
        "organization.read",
        "project.read",
        "project.write",
    },
    "viewer": {
        "organization.read",
        "project.read",
    },
}


@dataclass(frozen=True)
class AccessContext:
    user_id: str
    organization_id: str
    role: str


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
