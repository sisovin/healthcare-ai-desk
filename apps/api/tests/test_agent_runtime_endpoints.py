from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_db_session
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.main import app
from app.models import AgentExecutionApproval, AgentExecutionTask, AgentProfile, Organization, OrganizationMembership, User

ORG_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ORG_ID = "22222222-2222-2222-2222-222222222222"
OWNER_ID = "33333333-3333-3333-3333-333333333333"
ADMIN_ID = "33333333-3333-3333-3333-333333333334"
VIEWER_ID = "44444444-4444-4444-4444-444444444444"
OUTSIDER_ID = "55555555-5555-5555-5555-555555555555"
AGENT_ID = "66666666-6666-6666-6666-666666666666"


def _seed_db(db: Session) -> None:
    db.add_all(
        [
            Organization(id=ORG_ID, name="Org One", slug="org-one", is_active=True),
            Organization(id=OTHER_ORG_ID, name="Org Two", slug="org-two", is_active=True),
            User(
                id=OWNER_ID,
                email="owner-runtime@example.com",
                display_name="Owner Runtime",
                password_hash=hash_password("StrongPass123!"),
                is_active=True,
            ),
            User(
                id=ADMIN_ID,
                email="admin-runtime@example.com",
                display_name="Admin Runtime",
                password_hash=hash_password("StrongPass123!"),
                is_active=True,
            ),
            User(
                id=VIEWER_ID,
                email="viewer-runtime@example.com",
                display_name="Viewer Runtime",
                password_hash=hash_password("StrongPass123!"),
                is_active=True,
            ),
            User(
                id=OUTSIDER_ID,
                email="outsider-runtime@example.com",
                display_name="Outsider Runtime",
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
                user_id=ADMIN_ID,
                role="admin",
            ),
            OrganizationMembership(
                id=str(uuid4()),
                organization_id=ORG_ID,
                user_id=VIEWER_ID,
                role="viewer",
            ),
            AgentProfile(
                id=AGENT_ID,
                organization_id=ORG_ID,
                name="Runtime Agent",
                slug="runtime-agent",
                model_provider="openai",
                model_name="gpt-4o-mini",
                status="active",
                created_by_user_id=OWNER_ID,
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


def _publish_version(client: TestClient) -> None:
    publish = client.post(
        f"/api/v1/agent-runtime/agents/{AGENT_ID}/versions/publish",
        headers=_auth_headers(OWNER_ID, ORG_ID),
        json={},
    )
    assert publish.status_code == 201


def test_runtime_idempotency_retry_and_metrics_flow() -> None:
    for client, _ in _build_client():
        _publish_version(client)

        create_payload = {
            "input_payload": '{"token":"abc123","task":"demo"}',
            "initial_task_type": "analysis",
            "initial_task_payload": '{"password":"top-secret"}',
            "idempotency_key": "exec-key-001",
            "timeout_seconds": 600,
            "max_retries": 3,
        }
        first = client.post(
            f"/api/v1/agent-runtime/agents/{AGENT_ID}/executions",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json=create_payload,
        )
        assert first.status_code == 201
        first_row = first.json()
        execution_id = first_row["id"]
        assert "[REDACTED]" in first_row["input_payload"]

        second = client.post(
            f"/api/v1/agent-runtime/agents/{AGENT_ID}/executions",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json=create_payload,
        )
        assert second.status_code == 201
        assert second.json()["id"] == execution_id

        failed = client.patch(
            f"/api/v1/agent-runtime/executions/{execution_id}/status",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={
                "status": "failed",
                "failure_reason": "token=abc123 expired",
                "error_code": "UPSTREAM_TIMEOUT",
                "token_input_count": 120,
                "token_output_count": 64,
            },
        )
        assert failed.status_code == 200
        assert failed.json()["status"] == "failed"
        assert failed.json()["next_retry_at"] is not None

        retried = client.post(
            f"/api/v1/agent-runtime/executions/{execution_id}/retry",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"reason": "retry after timeout"},
        )
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"
        assert retried.json()["retry_count"] == 1

        running_again = client.patch(
            f"/api/v1/agent-runtime/executions/{execution_id}/status",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"status": "running"},
        )
        assert running_again.status_code == 200

        succeeded = client.patch(
            f"/api/v1/agent-runtime/executions/{execution_id}/status",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"status": "succeeded", "result_payload": '{"api_key":"x","ok":true}'},
        )
        assert succeeded.status_code == 200
        assert succeeded.json()["status"] == "succeeded"
        assert succeeded.json()["duration_ms"] is not None

        metrics = client.get(
            f"/api/v1/agent-runtime/executions/{execution_id}/metrics",
            headers=_auth_headers(OWNER_ID, ORG_ID),
        )
        assert metrics.status_code == 200
        assert metrics.json()["retry_count"] == 1
        assert metrics.json()["token_input_count"] == 120
        assert metrics.json()["last_error_code"] == "UPSTREAM_TIMEOUT"


def test_runtime_task_dependency_and_scheduling() -> None:
    for client, session_factory in _build_client():
        _publish_version(client)
        created = client.post(
            f"/api/v1/agent-runtime/agents/{AGENT_ID}/executions",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"initial_task_type": "task-a"},
        )
        assert created.status_code == 201
        execution_id = created.json()["id"]

        first_ready = client.get(
            f"/api/v1/agent-runtime/executions/{execution_id}/next-task",
            headers=_auth_headers(OWNER_ID, ORG_ID),
        )
        assert first_ready.status_code == 200
        first_task = first_ready.json()

        dependent = client.post(
            f"/api/v1/agent-runtime/executions/{execution_id}/tasks",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={
                "task_type": "task-b",
                "depends_on_task_id": first_task["id"],
            },
        )
        assert dependent.status_code == 201
        assert dependent.json()["status"] == "blocked"

        future_time = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        scheduled = client.post(
            f"/api/v1/agent-runtime/executions/{execution_id}/tasks",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"task_type": "task-c", "scheduled_at": future_time},
        )
        assert scheduled.status_code == 201

        with session_factory() as db:
            first_task_row = db.get(AgentExecutionTask, first_task["id"])
            first_task_row.status = "succeeded"
            db.add(first_task_row)
            db.commit()

        ready_after = client.get(
            f"/api/v1/agent-runtime/executions/{execution_id}/next-task",
            headers=_auth_headers(OWNER_ID, ORG_ID),
        )
        assert ready_after.status_code == 200
        assert ready_after.json()["task_type"] == "task-b"


def test_runtime_human_approval_expire_and_review() -> None:
    for client, session_factory in _build_client():
        _publish_version(client)
        created = client.post(
            f"/api/v1/agent-runtime/agents/{AGENT_ID}/executions",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"initial_task_type": "triage"},
        )
        execution_id = created.json()["id"]

        approval = client.post(
            f"/api/v1/agent-runtime/executions/{execution_id}/approvals",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"reason": "need approval", "expires_in_seconds": 600},
        )
        assert approval.status_code == 201
        approval_id = approval.json()["id"]

        with session_factory() as db:
            row = db.get(AgentExecutionApproval, approval_id)
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.add(row)
            db.commit()

        expire = client.post(
            "/api/v1/agent-runtime/approvals/expire",
            headers=_auth_headers(OWNER_ID, ORG_ID),
        )
        assert expire.status_code == 200
        assert expire.json()["expired_count"] == 1

        review_expired = client.patch(
            f"/api/v1/agent-runtime/approvals/{approval_id}",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"status": "approved"},
        )
        assert review_expired.status_code == 400


def test_m25_blocks_patient_identifiers_for_external_llms_and_gates_high_impact_work() -> None:
    for client, session_factory in _build_client():
        _publish_version(client)

        denied = client.post(
            f"/api/v1/agent-runtime/agents/{AGENT_ID}/executions",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={
                "initial_task_type": "reporting",
                "input_payload": '{"patient_id":"P-12345","summary":"follow-up"}',
            },
        )
        assert denied.status_code == 400
        assert "External LLM execution is denied" in denied.json()["detail"]

        created = client.post(
            f"/api/v1/agent-runtime/agents/{AGENT_ID}/executions",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"initial_task_type": "clinical_triage"},
        )
        assert created.status_code == 201
        execution_id = created.json()["id"]
        assert created.json()["status"] == "waiting_approval"

        bypass = client.patch(
            f"/api/v1/agent-runtime/executions/{execution_id}/status",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"status": "running"},
        )
        assert bypass.status_code == 400

        with session_factory() as db:
            approval = db.query(AgentExecutionApproval).filter_by(execution_id=execution_id).one()
            approval_id = approval.id

        self_review = client.patch(
            f"/api/v1/agent-runtime/approvals/{approval_id}",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"status": "approved"},
        )
        assert self_review.status_code == 400

        approved = client.patch(
            f"/api/v1/agent-runtime/approvals/{approval_id}",
            headers=_auth_headers(ADMIN_ID, ORG_ID, role="admin"),
            json={"status": "approved", "comment": "Reviewed by a separate authorized user."},
        )
        assert approved.status_code == 200

        running = client.patch(
            f"/api/v1/agent-runtime/executions/{execution_id}/status",
            headers=_auth_headers(OWNER_ID, ORG_ID),
            json={"status": "running"},
        )
        assert running.status_code == 200


def test_runtime_security_scope_and_permissions() -> None:
    for client, _ in _build_client():
        _publish_version(client)

        outsider = client.get(
            f"/api/v1/agent-runtime/agents/{AGENT_ID}/versions",
            headers=_auth_headers(OUTSIDER_ID, ORG_ID),
        )
        assert outsider.status_code == 403

        mismatch = client.get(
            f"/api/v1/agent-runtime/agents/{AGENT_ID}/versions",
            headers=_auth_headers(OWNER_ID, OTHER_ORG_ID) | {"X-Organization-Id": ORG_ID},
        )
        assert mismatch.status_code == 403

        viewer_execute = client.post(
            f"/api/v1/agent-runtime/agents/{AGENT_ID}/executions",
            headers=_auth_headers(VIEWER_ID, ORG_ID, role="viewer"),
            json={"initial_task_type": "triage"},
        )
        assert viewer_execute.status_code == 403

        viewer_expire = client.post(
            "/api/v1/agent-runtime/approvals/expire",
            headers=_auth_headers(VIEWER_ID, ORG_ID, role="viewer"),
        )
        assert viewer_expire.status_code == 403
