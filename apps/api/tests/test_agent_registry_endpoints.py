from collections.abc import Generator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_db_session
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.main import app
from app.models import AgentProfile, Organization, OrganizationMembership, User

ORG_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ORG_ID = "22222222-2222-2222-2222-222222222222"
OWNER_ID = "33333333-3333-3333-3333-333333333333"
VIEWER_ID = "44444444-4444-4444-4444-444444444444"
NON_MEMBER_ID = "55555555-5555-5555-5555-555555555555"


def _seed_db(db: Session) -> None:
    db.add_all(
        [
            Organization(id=ORG_ID, name="Org One", slug="org-one", is_active=True),
            Organization(id=OTHER_ORG_ID, name="Org Two", slug="org-two", is_active=True),
            User(
                id=OWNER_ID,
                email="owner@example.com",
                display_name="Owner",
                password_hash=hash_password("StrongPass123!"),
                is_active=True,
            ),
            User(
                id=VIEWER_ID,
                email="viewer@example.com",
                display_name="Viewer",
                password_hash=hash_password("StrongPass123!"),
                is_active=True,
            ),
            User(
                id=NON_MEMBER_ID,
                email="outsider@example.com",
                display_name="Outsider",
                password_hash=hash_password("StrongPass123!"),
                is_active=True,
            ),
            OrganizationMembership(
                id=str(uuid4()),
                organization_id=ORG_ID,
                user_id=OWNER_ID,
                role="owner",
            ),
            OrganizationMembership(
                id=str(uuid4()),
                organization_id=ORG_ID,
                user_id=VIEWER_ID,
                role="viewer",
            ),
        ]
    )
    db.commit()


def _auth_headers(user_id: str, org_id: str, role: str = "owner") -> dict[str, str]:
    token = create_access_token(subject=user_id, organization_id=org_id, role=role)
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org_id,
    }


def _build_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    with testing_session_factory() as db:
        _seed_db(db)

    def _override_db():
        db = testing_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = _override_db
    try:
        yield TestClient(app), testing_session_factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_create_list_get_and_update_agent_profile() -> None:
    for client, _ in _build_client():
        create_response = client.post(
            "/api/v1/agents",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={
                "name": "MNCH Coordinator",
                "slug": "mnch-coordinator",
                "model_provider": "openai",
                "model_name": "gpt-4o-mini",
                "status": "draft",
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["organization_id"] == ORG_ID
        assert created["created_by_user_id"] == OWNER_ID
        assert created["status"] == "draft"

        list_response = client.get("/api/v1/agents", headers=_auth_headers(OWNER_ID, ORG_ID))
        assert list_response.status_code == 200
        listed = list_response.json()
        assert len(listed) == 1
        assert listed[0]["id"] == created["id"]

        get_response = client.get(f"/api/v1/agents/{created['id']}", headers=_auth_headers(OWNER_ID, ORG_ID))
        assert get_response.status_code == 200
        assert get_response.json()["slug"] == "mnch-coordinator"

        patch_response = client.patch(
            f"/api/v1/agents/{created['id']}",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"status": "active", "name": "MNCH Team Coordinator"},
        )
        assert patch_response.status_code == 200
        patched = patch_response.json()
        assert patched["status"] == "active"
        assert patched["name"] == "MNCH Team Coordinator"


def test_create_requires_organization_header() -> None:
    for client, _ in _build_client():
        token = create_access_token(subject=OWNER_ID, organization_id=ORG_ID, role="owner")
        response = client.post(
            "/api/v1/agents",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Missing Header Agent",
                "slug": "missing-header-agent",
                "model_provider": "openai",
                "model_name": "gpt-4o-mini",
            },
        )
        assert response.status_code == 400
        assert "Missing required header" in response.json()["detail"]


def test_viewer_cannot_create_agent_but_can_list() -> None:
    for client, _ in _build_client():
        create_response = client.post(
            "/api/v1/agents",
            headers=_auth_headers(VIEWER_ID, ORG_ID),
            json={
                "name": "Unauthorized Create",
                "slug": "unauthorized-create",
                "model_provider": "openai",
                "model_name": "gpt-4o-mini",
            },
        )
        assert create_response.status_code == 403

        list_response = client.get("/api/v1/agents", headers=_auth_headers(VIEWER_ID, ORG_ID))
        assert list_response.status_code == 200
        assert list_response.json() == []


def test_get_blocks_cross_organization_access() -> None:
    for client, session_factory in _build_client():
        with session_factory() as db:
            cross_org_agent = AgentProfile(
                id=str(uuid4()),
                organization_id=OTHER_ORG_ID,
                name="Cross Org Agent",
                slug="cross-org-agent",
                model_provider="openai",
                model_name="gpt-4o-mini",
                status="active",
                created_by_user_id=OWNER_ID,
            )
            db.add(cross_org_agent)
            db.commit()
            cross_org_id = cross_org_agent.id

        response = client.get(f"/api/v1/agents/{cross_org_id}", headers=_auth_headers(OWNER_ID, ORG_ID))
        assert response.status_code == 404
        assert response.json()["detail"] == "Agent not found."


def test_list_rejects_malformed_organization_header() -> None:
    for client, _ in _build_client():
        response = client.get(
            "/api/v1/agents",
            headers={
                "Authorization": _auth_headers(OWNER_ID, ORG_ID)["Authorization"],
                "X-Organization-Id": "not-a-uuid",
            },
        )
        assert response.status_code == 400
        assert "Invalid X-Organization-Id format" in response.json()["detail"]


def test_list_rejects_token_organization_scope_mismatch() -> None:
    for client, _ in _build_client():
        mismatch_headers = _auth_headers(OWNER_ID, OTHER_ORG_ID)
        response = client.get(
            "/api/v1/agents",
            headers=mismatch_headers | {"X-Organization-Id": ORG_ID},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Token organization scope mismatch."


def test_list_rejects_non_member_user() -> None:
    for client, _ in _build_client():
        response = client.get(
            "/api/v1/agents",
            headers=_auth_headers(NON_MEMBER_ID, ORG_ID),
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "User is not a member of this organization."


def test_patch_rejects_viewer_write_permission() -> None:
    for client, session_factory in _build_client():
        with session_factory() as db:
            row = AgentProfile(
                id=str(uuid4()),
                organization_id=ORG_ID,
                name="Viewer Update Blocked",
                slug="viewer-update-blocked",
                model_provider="openai",
                model_name="gpt-4o-mini",
                status="active",
                created_by_user_id=OWNER_ID,
            )
            db.add(row)
            db.commit()
            agent_id = row.id

        response = client.patch(
            f"/api/v1/agents/{agent_id}",
            headers=_auth_headers(VIEWER_ID, ORG_ID, role="viewer"),
            json={"name": "Should Fail"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Insufficient permissions."
