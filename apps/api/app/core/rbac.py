from dataclasses import dataclass


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": {
        "organization.read",
        "organization.manage_members",
        "agent.read",
        "agent.write",
        "agent.assign",
        "agent.execute",
        "agent.approve",
        "agent.runtime.read",
        "project.read",
        "project.write",
        "project.manage_members",
        "audit.read",
    },
    "admin": {
        "organization.read",
        "organization.manage_members",
        "agent.read",
        "agent.write",
        "agent.assign",
        "agent.execute",
        "agent.approve",
        "agent.runtime.read",
        "project.read",
        "project.write",
        "project.manage_members",
        "audit.read",
    },
    "manager": {
        "organization.read",
        "agent.read",
        "agent.write",
        "agent.assign",
        "agent.execute",
        "agent.runtime.read",
        "project.read",
        "project.write",
        "project.manage_members",
    },
    "member": {
        "organization.read",
        "agent.read",
        "agent.execute",
        "agent.runtime.read",
        "project.read",
        "project.write",
    },
    "viewer": {
        "organization.read",
        "agent.read",
        "agent.runtime.read",
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
