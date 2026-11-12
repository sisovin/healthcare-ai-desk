from app.core.rbac import has_permission


def test_owner_has_high_privilege_permissions() -> None:
    assert has_permission("owner", "organization.manage_members") is True
    assert has_permission("owner", "audit.read") is True


def test_viewer_has_read_only_permissions() -> None:
    assert has_permission("viewer", "organization.read") is True
    assert has_permission("viewer", "project.read") is True
    assert has_permission("viewer", "project.write") is False


def test_unknown_role_has_no_permissions() -> None:
    assert has_permission("unknown", "organization.read") is False
