from collections.abc import Generator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.core.dependencies import get_db_session
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.main import app
from app.models import AgentProfile, AgentProjectAssignment, AgentVersion, Conversation, ConversationAuditLog, ConversationMember, ConversationMessage, ConversationTask, ConversationTaskDependency, Organization, OrganizationMembership, Project, SupervisorPlan, User, WorkflowEventConsumption, WorkflowOutboxEvent
from app.services.outbox_service import ack_after_commit, consume_event, lease_events, publish_leased_event, reclaim_pending_entries
from app.services.supervisor_service import PlanValidationError, create_plan

ORG_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_ORG_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OWNER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
OTHER_USER_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
PROJECT_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


def _seed(db: Session) -> None:
    db.add_all([
        Organization(id=ORG_ID, name="Conversation Org", slug="conversation-org", is_active=True),
        Organization(id=OTHER_ORG_ID, name="Other Org", slug="other-conversation-org", is_active=True),
        User(id=OWNER_ID, email="conversation-owner@example.com", display_name="Conversation Owner", password_hash=hash_password("StrongPass123!"), is_active=True),
        User(id=OTHER_USER_ID, email="conversation-other@example.com", display_name="Conversation Other", password_hash=hash_password("StrongPass123!"), is_active=True),
        OrganizationMembership(id=str(uuid4()), organization_id=ORG_ID, user_id=OWNER_ID, role="owner"),
        OrganizationMembership(id=str(uuid4()), organization_id=OTHER_ORG_ID, user_id=OTHER_USER_ID, role="owner"),
        Project(id=PROJECT_ID, organization_id=ORG_ID, name="Conversation Project", slug="conversation-project", status="active"),
    ])
    db.commit()


def _headers(user_id: str, org_id: str, role: str = "owner") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=user_id, organization_id=org_id, role=role)}", "X-Organization-Id": org_id}


def _client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    with factory() as db: _seed(db)
    def override():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db_session] = override
    try: yield TestClient(app), factory
    finally:
        app.dependency_overrides.clear(); Base.metadata.drop_all(engine)


def test_conversation_message_idempotency_tenant_scope_and_pii_redaction() -> None:
    for client, factory in _client():
        created = client.post("/api/v1/conversations", headers=_headers(OWNER_ID, ORG_ID), json={"project_id": PROJECT_ID, "title": "Monthly report"})
        assert created.status_code == 201
        conversation = created.json()
        message_payload = {"content": "patient_id=P-001; contact 012345678", "idempotency_key": "message-key-0001", "expected_state_version": 1}
        first = client.post(f"/api/v1/conversations/{conversation['id']}/messages", headers=_headers(OWNER_ID, ORG_ID), json=message_payload)
        assert first.status_code == 201
        assert "P-001" not in first.json()["content"]
        assert "012345678" not in first.json()["content"]
        second = client.post(f"/api/v1/conversations/{conversation['id']}/messages", headers=_headers(OWNER_ID, ORG_ID), json=message_payload)
        assert second.status_code == 201
        assert second.json()["id"] == first.json()["id"]
        changed = client.post(f"/api/v1/conversations/{conversation['id']}/messages", headers=_headers(OWNER_ID, ORG_ID), json={**message_payload, "content": "different"})
        assert changed.status_code == 409
        stale = client.post(f"/api/v1/conversations/{conversation['id']}/messages", headers=_headers(OWNER_ID, ORG_ID), json={"content": "new", "idempotency_key": "message-key-0002", "expected_state_version": 1})
        assert stale.status_code == 409
        hidden = client.get(f"/api/v1/conversations/{conversation['id']}", headers=_headers(OTHER_USER_ID, OTHER_ORG_ID))
        assert hidden.status_code == 404
        with factory() as db:
            row = db.get(ConversationMessage, first.json()["id"])
            assert row.content_ciphertext is not None and "P-001" not in row.content_ciphertext
            assert "P-001" not in row.content_redacted
            event = db.query(WorkflowOutboxEvent).filter_by(conversation_id=conversation["id"]).one()
            assert "P-001" not in event.payload and event.status == "pending"


def test_conversation_membership_and_dependency_constraints() -> None:
    for _client_instance, factory in _client():
        with factory() as db:
            conversation = Conversation(id=str(uuid4()), organization_id=ORG_ID, project_id=PROJECT_ID, created_by_user_id=OWNER_ID, title="Constraint test", status="active")
            db.add(conversation); db.flush()
            invalid_member = ConversationMember(id=str(uuid4()), organization_id=ORG_ID, conversation_id=conversation.id, member_type="user", user_id=None, agent_profile_id=None, membership_role="participant")
            db.add(invalid_member)
            try:
                db.commit()
                assert False, "exclusive identity check must reject an empty member identity"
            except IntegrityError:
                db.rollback()


class _RedisMock:
    def __init__(self, fail: bool = False): self.fail, self.entries, self.acks = fail, [], []
    def xadd(self, stream, fields):
        if self.fail: raise RuntimeError("redis unavailable")
        self.entries.append((stream, fields)); return "1-0"
    def xack(self, stream, group, entry_id): self.acks.append((stream, group, entry_id))
    def xautoclaim(self, stream, group, consumer, min_idle_ms, start_id, count): return ("0-0", [("1-0", {"event_id": "event"})], [])


def test_outbox_retry_publish_and_idempotent_consumer() -> None:
    for _client_instance, factory in _client():
        with factory() as db:
            conversation = Conversation(id=str(uuid4()), organization_id=ORG_ID, project_id=PROJECT_ID, created_by_user_id=OWNER_ID, title="Outbox", status="active")
            event = WorkflowOutboxEvent(id=str(uuid4()), organization_id=ORG_ID, conversation_id=conversation.id, aggregate_type="conversation", aggregate_id=conversation.id, event_type="test", payload="{}", idempotency_key="outbox-key", max_attempts=2)
            db.add_all([conversation, event]); db.commit()
            leased = lease_events(db, publisher_id="publisher-a")
            assert leased[0].id == event.id
            assert not publish_leased_event(db, event_id=event.id, publisher_id="publisher-a", redis_client=_RedisMock(fail=True))
            event = db.get(WorkflowOutboxEvent, event.id); event.next_attempt_at = event.next_attempt_at.replace(year=2000); db.commit()
            leased = lease_events(db, publisher_id="publisher-b")
            redis = _RedisMock()
            assert publish_leased_event(db, event_id=leased[0].id, publisher_id="publisher-b", redis_client=redis)
            calls = []
            assert consume_event(db, organization_id=ORG_ID, event_id=event.id, consumer_name="test", handler=lambda _db, _event: calls.append(_event.id))
            assert not consume_event(db, organization_id=ORG_ID, event_id=event.id, consumer_name="test", handler=lambda _db, _event: calls.append(_event.id))
            ack_after_commit(redis, stream="healthcare:workflow-events", group="test-group", entry_id="1-0")
            assert calls == [event.id] and redis.acks == [("healthcare:workflow-events", "test-group", "1-0")]
            assert reclaim_pending_entries(redis, stream="healthcare:workflow-events", group="test-group", consumer="recovery") == [("1-0", {"event_id": "event"})]


def test_m314_fault_injection_lease_fencing_dedup_and_sanitization() -> None:
    for _client_instance, factory in _client():
        with factory() as db:
            conversation = Conversation(id=str(uuid4()), organization_id=ORG_ID, project_id=PROJECT_ID, created_by_user_id=OWNER_ID, title="Faults", status="active")
            event = WorkflowOutboxEvent(id=str(uuid4()), organization_id=ORG_ID, conversation_id=conversation.id, aggregate_type="conversation", aggregate_id=conversation.id, event_type="test", payload="{}", idempotency_key="fault-key", max_attempts=1)
            db.add_all([conversation, event]); db.commit()
            lease_events(db, publisher_id="publisher-a", lease_seconds=1)
            event = db.get(WorkflowOutboxEvent, event.id); event.lease_expires_at = event.lease_expires_at.replace(year=2000); db.commit()
            redis = _RedisMock()
            assert not publish_leased_event(db, event_id=event.id, publisher_id="publisher-a", redis_client=redis)  # FI-01/FI-06
            lease_events(db, publisher_id="publisher-b")
            assert not publish_leased_event(db, event_id=event.id, publisher_id="publisher-a", redis_client=redis)  # FI-02
            assert publish_leased_event(db, event_id=event.id, publisher_id="publisher-b", redis_client=redis)
            side_effects = []
            assert consume_event(db, organization_id=ORG_ID, event_id=event.id, consumer_name="dedup", handler=lambda _db, _event: side_effects.append(1))
            assert not consume_event(db, organization_id=ORG_ID, event_id=event.id, consumer_name="dedup", handler=lambda _db, _event: side_effects.append(1))  # FI-03
            assert side_effects == [1]
            failed = WorkflowOutboxEvent(id=str(uuid4()), organization_id=ORG_ID, conversation_id=conversation.id, aggregate_type="conversation", aggregate_id=conversation.id, event_type="test", payload="{}", idempotency_key="secret-fault", max_attempts=1)
            db.add(failed); db.commit(); lease_events(db, publisher_id="publisher-c")
            class SecretRedis: 
                def xadd(self, *_args, **_kwargs): raise RuntimeError("redis://user:super-secret@example")
            assert not publish_leased_event(db, event_id=failed.id, publisher_id="publisher-c", redis_client=SecretRedis())
            assert "super-secret" not in (db.get(WorkflowOutboxEvent, failed.id).last_error_message or "")  # FI-05


def test_m314_fi04_handler_failure_rolls_back_ledger_and_side_effect() -> None:
    for _client_instance, factory in _client():
        with factory() as db:
            conversation = Conversation(id=str(uuid4()), organization_id=ORG_ID, project_id=PROJECT_ID, created_by_user_id=OWNER_ID, title="Rollback", status="active")
            event = WorkflowOutboxEvent(id=str(uuid4()), organization_id=ORG_ID, conversation_id=conversation.id, aggregate_type="conversation", aggregate_id=conversation.id, event_type="test", payload="{}", idempotency_key="rollback-key")
            db.add_all([conversation, event]); db.commit()
            def failing_handler(session, _event):
                session.add(ConversationAuditLog(id=str(uuid4()), organization_id=ORG_ID, conversation_id=conversation.id, action="test.side_effect", actor_type="system"))
                session.flush()
                raise RuntimeError("injected handler failure")
            with pytest.raises(RuntimeError, match="injected"):
                consume_event(db, organization_id=ORG_ID, event_id=event.id, consumer_name="rollback", handler=failing_handler)
            assert db.query(WorkflowEventConsumption).filter_by(event_id=event.id, consumer_name="rollback").count() == 0
            assert db.query(ConversationAuditLog).filter_by(conversation_id=conversation.id, action="test.side_effect").count() == 0
            assert db.get(WorkflowOutboxEvent, event.id).status == "pending"
            # The service rolled back; this query proves the same session is usable.
            assert db.query(Conversation).filter_by(id=conversation.id).one().title == "Rollback"


def test_supervisor_plan_dag_eligibility_approval_and_rollback() -> None:
    for _client_instance, factory in _client():
        with factory() as db:
            conversation = Conversation(id=str(uuid4()), organization_id=ORG_ID, project_id=PROJECT_ID, created_by_user_id=OWNER_ID, title="Supervisor", status="active")
            db.add(conversation); db.flush()
            db.add(ConversationMember(id=str(uuid4()), organization_id=ORG_ID, conversation_id=conversation.id, member_type="user", user_id=OWNER_ID, membership_role="owner"))
            agent = AgentProfile(id=str(uuid4()), organization_id=ORG_ID, name="Clinical", slug="clinical", model_provider="openai", model_name="model", role="clinical", status="active", created_by_user_id=OWNER_ID)
            db.add(agent); db.flush()
            db.add_all([AgentProjectAssignment(id=str(uuid4()), organization_id=ORG_ID, agent_profile_id=agent.id, project_id=PROJECT_ID, assigned_by_user_id=OWNER_ID), AgentVersion(id=str(uuid4()), organization_id=ORG_ID, agent_profile_id=agent.id, version_number=1, is_published=True, snapshot_name="Clinical", snapshot_model_provider="openai", snapshot_model_name="model", published_by_user_id=OWNER_ID)])
            db.commit()
            cyclic = [{"key":"a","agent_id":agent.id,"task_type":"reporting","depends_on":["b"],"required_capabilities":["clinical"]},{"key":"b","agent_id":agent.id,"task_type":"reporting","depends_on":["a"],"required_capabilities":["clinical"]}]
            with pytest.raises(PlanValidationError, match="cycle"):
                create_plan(db, organization_id=ORG_ID, conversation_id=conversation.id, actor_user_id=OWNER_ID, goal="cycle", strategy="sequential", tasks=cyclic)
            bad = [{"key":"bad","agent_id":"ffffffff-ffff-ffff-ffff-ffffffffffff","task_type":"reporting","depends_on":[],"required_capabilities":[]}]
            with pytest.raises(PlanValidationError, match="active and assigned"):
                create_plan(db, organization_id=ORG_ID, conversation_id=conversation.id, actor_user_id=OWNER_ID, goal="bad", strategy="sequential", tasks=bad)
            assert db.query(SupervisorPlan).count() == 0
            plan = create_plan(db, organization_id=ORG_ID, conversation_id=conversation.id, actor_user_id=OWNER_ID, goal="triage", strategy="sequential", tasks=[{"key":"triage","agent_id":agent.id,"task_type":"clinical_triage","depends_on":[],"required_capabilities":["clinical"]}])
            task = db.query(ConversationTask).filter_by(task_key="triage").one()
            assert plan.status == "validated" and task.status == "waiting_approval"


def test_supervisor_runtime_fault_sqlite_smoke(monkeypatch) -> None:
    """SQLite smoke test only; MySQL FI-07/FI-08 evidence lives in its own module."""
    import app.services.supervisor_service as supervisor_module
    import app.services.agent_runtime_engine as runtime_module
    for _client_instance, factory in _client():
        with factory() as db:
            conversation = Conversation(id=str(uuid4()), organization_id=ORG_ID, project_id=PROJECT_ID, created_by_user_id=OWNER_ID, title="FI", status="active")
            agent = AgentProfile(id=str(uuid4()), organization_id=ORG_ID, name="FI Agent", slug="fi-agent", model_provider="openai", model_name="model", role="clinical", status="active", created_by_user_id=OWNER_ID)
            db.add_all([conversation, ConversationMember(id=str(uuid4()), organization_id=ORG_ID, conversation_id=conversation.id, member_type="user", user_id=OWNER_ID, membership_role="owner"), agent]); db.flush()
            db.add_all([AgentProjectAssignment(id=str(uuid4()), organization_id=ORG_ID, agent_profile_id=agent.id, project_id=PROJECT_ID, assigned_by_user_id=OWNER_ID), AgentVersion(id=str(uuid4()), organization_id=ORG_ID, agent_profile_id=agent.id, version_number=1, is_published=True, snapshot_name="FI", snapshot_model_provider="openai", snapshot_model_name="model", published_by_user_id=OWNER_ID)]); db.commit()
            baseline = {x.id for x in db.query(SupervisorPlan).all()}
            monkeypatch.setattr(supervisor_module, "start_execution", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("runtime fault after plan flush")))
            with pytest.raises(RuntimeError): create_plan(db, organization_id=ORG_ID, conversation_id=conversation.id, actor_user_id=OWNER_ID, goal="x", strategy="sequential", tasks=[{"key":"x","agent_id":agent.id,"task_type":"reporting","depends_on":[],"required_capabilities":["clinical"]}])
        with factory() as fresh:
            assert {x.id for x in fresh.query(SupervisorPlan).all()} == baseline
