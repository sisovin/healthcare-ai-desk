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
        "conversation.read",
        "conversation.write",
        "conversation.manage",
        "conversation.audit.read",
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
        "conversation.read",
        "conversation.write",
        "conversation.manage",
        "conversation.audit.read",
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
        "conversation.read",
        "conversation.write",
        "conversation.manage",
    },
    "member": {
        "organization.read",
        "agent.read",
        "agent.execute",
        "agent.runtime.read",
        "project.read",
        "project.write",
        "conversation.read",
        "conversation.write",
    },
    "viewer": {
        "organization.read",
        "agent.read",
        "agent.runtime.read",
        "project.read",
        "conversation.read",
    },
}


@dataclass(frozen=True)
class AccessContext:
    user_id: str
    organization_id: str
    role: str


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
