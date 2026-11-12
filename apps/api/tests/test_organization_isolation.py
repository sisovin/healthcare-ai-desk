from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.dependencies import get_db_session
from app.main import app


class _FakeSession:
    def __init__(self, organizations: dict[str, object]):
        self._organizations = organizations

    def get(self, _model, key: str):
        return self._organizations.get(key)

    def close(self) -> None:
        return None


def _override_db_with_organizations(organizations: dict[str, object]):
    def _override():
        session = _FakeSession(organizations)
        try:
            yield session
        finally:
            session.close()

    return _override


def test_scope_check_requires_organization_header() -> None:
    app.dependency_overrides[get_db_session] = _override_db_with_organizations({})
    client = TestClient(app)
    response = client.get("/api/v1/organizations/11111111-1111-1111-1111-111111111111/scope")
    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert "Missing required header" in response.json()["detail"]


def test_scope_check_rejects_invalid_organization_header() -> None:
    app.dependency_overrides[get_db_session] = _override_db_with_organizations({})
    client = TestClient(app)
    response = client.get(
        "/api/v1/organizations/11111111-1111-1111-1111-111111111111/scope",
        headers={"X-Organization-Id": "not-a-uuid"},
    )
    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert "Invalid X-Organization-Id format" in response.json()["detail"]


def test_scope_check_rejects_unknown_organization() -> None:
    app.dependency_overrides[get_db_session] = _override_db_with_organizations({})
    client = TestClient(app)
    response = client.get(
        "/api/v1/organizations/11111111-1111-1111-1111-111111111111/scope",
        headers={"X-Organization-Id": "11111111-1111-1111-1111-111111111111"},
    )
    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found or inactive."


def test_scope_check_rejects_cross_organization_access() -> None:
    app.dependency_overrides[get_db_session] = _override_db_with_organizations(
        {"11111111-1111-1111-1111-111111111111": SimpleNamespace(is_active=True)}
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/organizations/22222222-2222-2222-2222-222222222222/scope",
        headers={"X-Organization-Id": "11111111-1111-1111-1111-111111111111"},
    )
    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-organization access is forbidden."


def test_scope_check_allows_same_organization_access() -> None:
    app.dependency_overrides[get_db_session] = _override_db_with_organizations(
        {"11111111-1111-1111-1111-111111111111": SimpleNamespace(is_active=True)}
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/organizations/11111111-1111-1111-1111-111111111111/scope",
        headers={"X-Organization-Id": "11111111-1111-1111-1111-111111111111"},
    )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "organization_id": "11111111-1111-1111-1111-111111111111",
        "isolation": "enforced",
    }
