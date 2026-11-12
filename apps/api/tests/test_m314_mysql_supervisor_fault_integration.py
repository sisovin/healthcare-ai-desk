"""M3.1.4 FI-07/FI-08: real MySQL, independent-session rollback evidence."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from queue import Queue
from threading import Barrier, Thread
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.session import SessionLocal, engine
from app.models import (
    AgentExecution,
    AgentExecutionApproval,
    AgentExecutionAuditLog,
    AgentExecutionTask,
    AgentProfile,
    AgentProjectAssignment,
    AgentVersion,
    Conversation,
    ConversationAuditLog,
    ConversationMember,
    ConversationTask,
    ConversationTaskDependency,
    Organization,
    OrganizationMembership,
    Project,
    SupervisorPlan,
    User,
    WorkflowOutboxEvent,
    WorkflowEventConsumption,
)
from app.core.dependencies import get_redis_client
from app.services.agent_runtime_engine import RuntimeValidationError, review_execution_approval, start_execution
from app.services.outbox_service import ack_after_commit, consume_event, lease_events, publish_leased_event, reclaim_pending_entries
from app.services.supervisor_service import PlanValidationError, create_plan
from app.services.conversation_service import append_user_message
from app.main import app


def _ids(db: Session, model, organization_id: str) -> set[str]:
    return set(db.scalars(select(model.id).where(model.organization_id == organization_id)).all())


def _five_table_ids(db: Session, organization_id: str) -> dict[str, set[str]]:
    return {
        "plans": _ids(db, SupervisorPlan, organization_id),
        "tasks": _ids(db, ConversationTask, organization_id),
        "executions": _ids(db, AgentExecution, organization_id),
        "approvals": _ids(db, AgentExecutionApproval, organization_id),
        "outbox": _ids(db, WorkflowOutboxEvent, organization_id),
    }


@pytest.fixture
def mysql_supervisor_scope() -> Generator[dict[str, str], None, None]:
    """Create and remove only a UUID-namespaced test tenant; never resets volumes."""
    assert engine.dialect.name == "mysql", "FI-07/FI-08 require MySQL; SQLite is not evidence"
    suffix = uuid4().hex
    scope = {key: str(uuid4()) for key in ("organization_id", "user_id", "reviewer_a_id", "reviewer_b_id", "supervisor_id", "project_id", "other_project_id", "conversation_id", "agent_id")}
    with SessionLocal() as db:
        db.add_all([
            Organization(id=scope["organization_id"], name=f"M314 {suffix}", slug=f"m314-{suffix}", is_active=True),
            User(id=scope["user_id"], email=f"m314-{suffix}@invalid.test", display_name="M314 Test", password_hash="not-used", is_active=True),
            User(id=scope["reviewer_a_id"], email=f"m314-a-{suffix}@invalid.test", display_name="M314 Reviewer A", password_hash="not-used", is_active=True),
            User(id=scope["reviewer_b_id"], email=f"m314-b-{suffix}@invalid.test", display_name="M314 Reviewer B", password_hash="not-used", is_active=True),
            User(id=scope["supervisor_id"], email=f"m314-supervisor-{suffix}@invalid.test", display_name="M314 Supervisor", password_hash="not-used", is_active=True),
        ])
        db.flush()
        db.add_all([
            OrganizationMembership(id=str(uuid4()), organization_id=scope["organization_id"], user_id=scope["user_id"], role="owner"),
            OrganizationMembership(id=str(uuid4()), organization_id=scope["organization_id"], user_id=scope["reviewer_a_id"], role="owner"),
            OrganizationMembership(id=str(uuid4()), organization_id=scope["organization_id"], user_id=scope["reviewer_b_id"], role="owner"),
            OrganizationMembership(id=str(uuid4()), organization_id=scope["organization_id"], user_id=scope["supervisor_id"], role="manager"),
            Project(id=scope["project_id"], organization_id=scope["organization_id"], name="M314", slug=f"m314-{suffix}", status="active"),
            Project(id=scope["other_project_id"], organization_id=scope["organization_id"], name="M314 Other", slug=f"m314-other-{suffix}", status="active"),
            AgentProfile(id=scope["agent_id"], organization_id=scope["organization_id"], name="M314 Agent", slug=f"m314-agent-{suffix}", model_provider="openai", model_name="test", role="clinical", status="active", created_by_user_id=scope["user_id"]),
        ])
        db.flush()
        db.add_all([
            Conversation(id=scope["conversation_id"], organization_id=scope["organization_id"], project_id=scope["project_id"], created_by_user_id=scope["user_id"], title="M314 fault test", status="active"),
            AgentProjectAssignment(id=str(uuid4()), organization_id=scope["organization_id"], agent_profile_id=scope["agent_id"], project_id=scope["project_id"], assigned_by_user_id=scope["user_id"]),
            AgentVersion(id=str(uuid4()), organization_id=scope["organization_id"], agent_profile_id=scope["agent_id"], version_number=1, is_published=True, snapshot_name="M314 Agent", snapshot_model_provider="openai", snapshot_model_name="test", published_by_user_id=scope["user_id"]),
        ])
        db.flush()
        db.add(ConversationMember(id=str(uuid4()), organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], member_type="user", user_id=scope["user_id"], membership_role="owner"))
        db.commit()
    try:
        yield scope
    finally:
        # This is a narrowly-scoped cleanup of the tenant created by this fixture.
        with SessionLocal() as db:
            org_id = scope["organization_id"]
            # Delete child rows explicitly because conversations/projects use RESTRICT.
            for model in (
                WorkflowOutboxEvent,
                WorkflowEventConsumption,
                SupervisorPlan,
                ConversationTaskDependency,
                ConversationTask,
                ConversationMember,
                ConversationAuditLog,
                Conversation,
                AgentExecutionApproval,
                AgentExecutionAuditLog,
                AgentExecutionTask,
                AgentExecution,
                AgentProjectAssignment,
                AgentVersion,
                AgentProfile,
                Project,
                OrganizationMembership,
            ):
                db.execute(delete(model).where(model.organization_id == org_id))
            db.execute(delete(Organization).where(Organization.id == scope["organization_id"]))
            db.execute(delete(User).where(User.id.in_((scope["user_id"], scope["reviewer_a_id"], scope["reviewer_b_id"], scope["supervisor_id"]))))
            db.commit()


def _plan_task(scope: dict[str, str], task_type: str) -> list[dict]:
    return [{"key": f"m314-{uuid4().hex}", "agent_id": scope["agent_id"], "task_type": task_type, "depends_on": [], "required_capabilities": ["clinical"]}]


def test_m314_fi07_runtime_rollback_after_supervisor_flushes(mysql_supervisor_scope, monkeypatch) -> None:
    """FI-07: plan/runtime/conversation task are flushed, then one transaction rolls back."""
    import app.services.supervisor_service as supervisor_module

    scope = mysql_supervisor_scope
    with SessionLocal() as baseline_session:
        baseline = _five_table_ids(baseline_session, scope["organization_id"])

    proof: dict[str, set[str]] = {}

    def fail_after_flush(db: Session, *, plan: SupervisorPlan, tasks: dict[str, ConversationTask]) -> None:
        # This executes inside create_plan's original MySQL transaction after both
        # start_execution(commit=False) and the ConversationTask flush.
        proof["plans"] = _ids(db, SupervisorPlan, scope["organization_id"])
        proof["tasks"] = _ids(db, ConversationTask, scope["organization_id"])
        proof["executions"] = _ids(db, AgentExecution, scope["organization_id"])
        assert plan.id in proof["plans"]
        assert {row.id for row in tasks.values()}.issubset(proof["tasks"])
        assert {row.execution_id for row in tasks.values()}.issubset(proof["executions"])
        raise RuntimeError("FI-07 post-flush runtime fault")

    monkeypatch.setattr(supervisor_module, "_after_supervisor_records_flushed", fail_after_flush)
    original = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="FI-07 post-flush"):
            create_plan(original, organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], actor_user_id=scope["user_id"], goal="FI-07", strategy="sequential", tasks=_plan_task(scope, "reporting"))
        assert proof["plans"] - baseline["plans"]
        assert proof["tasks"] - baseline["tasks"]
        assert proof["executions"] - baseline["executions"]
    finally:
        original.close()

    # A fresh MySQL session/connection sees no IDs introduced by the failed transaction.
    with SessionLocal() as verification_session:
        assert _five_table_ids(verification_session, scope["organization_id"]) == baseline


def test_m314_fi08_approval_rollback_after_policy_approval_flush(mysql_supervisor_scope, monkeypatch) -> None:
    """FI-08: M2.5 policy is evaluated; its real approval creator flushes then fails."""
    import app.services.agent_runtime_engine as runtime_module

    scope = mysql_supervisor_scope
    with SessionLocal() as baseline_session:
        baseline = _five_table_ids(baseline_session, scope["organization_id"])

    original_approval_creator = runtime_module._create_policy_approval
    proof: dict[str, set[str]] = {}

    def fail_after_real_approval_flush(db: Session, **kwargs):
        approval = original_approval_creator(db, **kwargs)
        db.flush()
        proof["executions"] = _ids(db, AgentExecution, scope["organization_id"])
        proof["approvals"] = _ids(db, AgentExecutionApproval, scope["organization_id"])
        assert kwargs["execution_id"] in proof["executions"]
        assert approval.id in proof["approvals"]
        raise RuntimeError("FI-08 approval creation fault")

    monkeypatch.setattr(runtime_module, "_create_policy_approval", fail_after_real_approval_flush)
    original = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="FI-08 approval"):
            create_plan(original, organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], actor_user_id=scope["user_id"], goal="FI-08", strategy="sequential", tasks=_plan_task(scope, "clinical_triage"))
        assert proof["executions"] - baseline["executions"]
        assert proof["approvals"] - baseline["approvals"]
    finally:
        original.close()

    # Independent connection: no plan, task, execution, approval, or outbox ID persisted.
    with SessionLocal() as verification_session:
        assert _five_table_ids(verification_session, scope["organization_id"]) == baseline


def test_m314_fi09_mysql_commit_before_xack_reclaim_deduplicates(mysql_supervisor_scope) -> None:
    """FI-09: a committed side effect survives failed XACK but is never repeated."""
    scope = mysql_supervisor_scope
    redis = get_redis_client()
    stream, group = f"had:test:m314:fi09:{uuid4()}", "m314-fi09"
    event_id = str(uuid4())
    try:
        with SessionLocal() as setup:
            event = WorkflowOutboxEvent(
                id=event_id,
                organization_id=scope["organization_id"],
                conversation_id=scope["conversation_id"],
                aggregate_type="conversation",
                aggregate_id=scope["conversation_id"],
                event_type="m314.fi09",
                payload="{}",
                idempotency_key=f"m314-fi09:{uuid4()}",
            )
            setup.add(event)
            setup.commit()

        redis.xgroup_create(stream, group, id="0-0", mkstream=True)
        entry_id = redis.xadd(stream, {"event_id": event_id, "organization_id": scope["organization_id"]})
        delivered = redis.xreadgroup(group, "worker-before-xack", {stream: ">"}, count=1, block=1000)
        assert delivered and delivered[0][1][0][0] == entry_id

        def add_side_effect(db: Session, _event: WorkflowOutboxEvent) -> None:
            db.add(ConversationAuditLog(
                id=str(uuid4()), organization_id=scope["organization_id"],
                conversation_id=scope["conversation_id"], action="m314.fi09.side_effect", actor_type="system",
            ))

        # The MySQL side effect and consumption ledger commit together before XACK.
        first_consumer = SessionLocal()
        try:
            assert consume_event(first_consumer, organization_id=scope["organization_id"], event_id=event_id, consumer_name="m314-fi09", handler=add_side_effect)
        finally:
            first_consumer.close()

        with SessionLocal() as committed:
            assert committed.query(WorkflowEventConsumption).filter_by(organization_id=scope["organization_id"], event_id=event_id, consumer_name="m314-fi09").count() == 1
            assert committed.query(ConversationAuditLog).filter_by(organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], action="m314.fi09.side_effect").count() == 1

        class FailingXack:
            def xack(self, *_args, **_kwargs):
                raise RuntimeError("FI-09 injected XACK failure")

        with pytest.raises(RuntimeError, match="FI-09 injected XACK failure"):
            ack_after_commit(FailingXack(), stream=stream, group=group, entry_id=entry_id)

        reclaimed = reclaim_pending_entries(redis, stream=stream, group=group, consumer="worker-recovery", min_idle_ms=0)
        assert any(item[0] == entry_id for item in reclaimed)

        retry_consumer = SessionLocal()
        try:
            assert not consume_event(retry_consumer, organization_id=scope["organization_id"], event_id=event_id, consumer_name="m314-fi09", handler=add_side_effect)
        finally:
            retry_consumer.close()
        ack_after_commit(redis, stream=stream, group=group, entry_id=entry_id)

        # Fresh MySQL connection proves replay created neither a second ledger nor side effect.
        with SessionLocal() as verification:
            assert verification.query(WorkflowEventConsumption).filter_by(organization_id=scope["organization_id"], event_id=event_id, consumer_name="m314-fi09").count() == 1
            assert verification.query(ConversationAuditLog).filter_by(organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], action="m314.fi09.side_effect").count() == 1
    finally:
        redis.delete(stream)


def test_m314_fi10_concurrent_human_approval_decision_is_single_terminal(mysql_supervisor_scope) -> None:
    """FI-10: two authorized reviewers race; one terminal decision wins."""
    scope = mysql_supervisor_scope
    with SessionLocal() as setup:
        execution = start_execution(
            setup,
            organization_id=scope["organization_id"],
            agent_id=scope["agent_id"],
            requested_by_user_id=scope["user_id"],
            project_id=scope["project_id"],
            input_payload=None,
            initial_task_type="clinical_triage",
            initial_task_payload=None,
            idempotency_key=f"m314-fi10:{uuid4()}",
            timeout_seconds=900,
            max_retries=0,
        )
        approval = setup.query(AgentExecutionApproval).filter_by(organization_id=scope["organization_id"], execution_id=execution.id, status="pending").one()
        approval_id, execution_id = approval.id, execution.id

    # Requester is never a reviewer, even before the concurrent race begins.
    with SessionLocal() as self_review:
        with pytest.raises(RuntimeValidationError, match="requester cannot"):
            review_execution_approval(self_review, organization_id=scope["organization_id"], approval_id=approval_id, reviewer_user_id=scope["user_id"], status="approved", comment="self")

    barrier, results = Barrier(2), Queue()

    def review_as(reviewer_user_id: str, decision: str) -> None:
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            reviewed = review_execution_approval(db, organization_id=scope["organization_id"], approval_id=approval_id, reviewer_user_id=reviewer_user_id, status=decision, comment=f"FI-10 {decision}")
            results.put(("committed", reviewer_user_id, reviewed.status))
        except RuntimeValidationError as exc:
            results.put(("conflict", reviewer_user_id, str(exc)))
        finally:
            db.close()

    first = Thread(target=review_as, args=(scope["reviewer_a_id"], "approved"))
    second = Thread(target=review_as, args=(scope["reviewer_b_id"], "rejected"))
    first.start(); second.start(); first.join(timeout=15); second.join(timeout=15)
    assert not first.is_alive() and not second.is_alive()
    outcomes = [results.get_nowait(), results.get_nowait()]
    assert sum(outcome[0] == "committed" for outcome in outcomes) == 1
    assert sum(outcome[0] == "conflict" and "already finalized" in outcome[2] for outcome in outcomes) == 1

    # Fresh connection confirms one reviewer, one terminal approval, and no unauthorized execution state.
    with SessionLocal() as verification:
        approval = verification.get(AgentExecutionApproval, approval_id)
        execution = verification.get(AgentExecution, execution_id)
        assert approval.status in {"approved", "rejected"}
        assert approval.reviewer_user_id in {scope["reviewer_a_id"], scope["reviewer_b_id"]}
        assert execution.status == ("queued" if approval.status == "approved" else "cancelled")
        reviews = verification.query(AgentExecutionAuditLog).filter_by(organization_id=scope["organization_id"], execution_id=execution_id, action="approval.reviewed").all()
        assert len(reviews) == 1


def test_m314_fi10_supervisor_role_cannot_review_approval(mysql_supervisor_scope) -> None:
    """The API RBAC boundary denies a supervisor-equivalent manager approval authority."""
    scope = mysql_supervisor_scope
    with SessionLocal() as setup:
        execution = start_execution(
            setup, organization_id=scope["organization_id"], agent_id=scope["agent_id"], requested_by_user_id=scope["user_id"],
            project_id=scope["project_id"], input_payload=None, initial_task_type="clinical_triage", initial_task_payload=None,
            idempotency_key=f"m314-fi10-supervisor:{uuid4()}", timeout_seconds=900, max_retries=0,
        )
        approval_id = setup.query(AgentExecutionApproval).filter_by(organization_id=scope["organization_id"], execution_id=execution.id, status="pending").one().id
    token = create_access_token(subject=scope["supervisor_id"], organization_id=scope["organization_id"], role="manager")
    with TestClient(app) as client:
        response = client.patch(
            f"/api/v1/agent-runtime/approvals/{approval_id}",
            headers={"Authorization": f"Bearer {token}", "X-Organization-Id": scope["organization_id"]},
            json={"status": "approved", "comment": "not authorized"},
        )
    assert response.status_code == 403
    with SessionLocal() as verification:
        assert verification.get(AgentExecutionApproval, approval_id).status == "pending"


def _new_outbox_event(scope: dict[str, str], suffix: str) -> str:
    event_id = str(uuid4())
    with SessionLocal() as db:
        db.add(WorkflowOutboxEvent(
            id=event_id, organization_id=scope["organization_id"], conversation_id=scope["conversation_id"],
            aggregate_type="conversation", aggregate_id=scope["conversation_id"], event_type=f"m314.{suffix}",
            payload="{}", idempotency_key=f"m314:{suffix}:{uuid4()}",
        ))
        db.commit()
    return event_id


def test_m314_concurrent_publishers_lease_once_and_fence_expiry(mysql_supervisor_scope) -> None:
    """Two MySQL publishers race one event; only the live lease owner may publish."""
    scope = mysql_supervisor_scope
    event_id = _new_outbox_event(scope, "publisher-race")
    barrier, results = Barrier(2), Queue()

    def claim(publisher_id: str) -> None:
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            results.put((publisher_id, [event.id for event in lease_events(db, publisher_id=publisher_id, limit=1, lease_seconds=60)]))
        finally:
            db.close()

    first, second = Thread(target=claim, args=("m314-publisher-a",)), Thread(target=claim, args=("m314-publisher-b",))
    first.start(); second.start(); first.join(timeout=15); second.join(timeout=15)
    assert not first.is_alive() and not second.is_alive()
    claims = [results.get_nowait(), results.get_nowait()]
    winners = [publisher for publisher, ids in claims if event_id in ids]
    assert len(winners) == 1
    old_owner = winners[0]

    # Expire the original lease and transfer it; the old publisher is fenced before XADD.
    with SessionLocal() as expiry:
        row = expiry.get(WorkflowOutboxEvent, event_id)
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        expiry.commit()
    with SessionLocal() as replacement:
        replacement_claim = lease_events(replacement, publisher_id="m314-publisher-replacement", limit=1, lease_seconds=60)
        assert [row.id for row in replacement_claim] == [event_id]

    redis = get_redis_client()
    stream = f"had:test:m314:publisher:{uuid4()}"
    try:
        with SessionLocal() as stale:
            assert not publish_leased_event(stale, event_id=event_id, publisher_id=old_owner, redis_client=redis, stream=stream)
        with SessionLocal() as current:
            assert publish_leased_event(current, event_id=event_id, publisher_id="m314-publisher-replacement", redis_client=redis, stream=stream)
        with SessionLocal() as verification:
            row = verification.get(WorkflowOutboxEvent, event_id)
            assert row.status == "published" and row.lease_owner is None and row.lease_expires_at is None
    finally:
        redis.delete(stream)


def test_m314_concurrent_consumers_commit_one_side_effect(mysql_supervisor_scope) -> None:
    """Two independent MySQL consumers contend on one ledger unique key."""
    scope = mysql_supervisor_scope
    event_id = _new_outbox_event(scope, "consumer-race")
    barrier, results = Barrier(2), Queue()

    def consume(consumer_label: str) -> None:
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            def side_effect(session: Session, _event: WorkflowOutboxEvent) -> None:
                session.add(ConversationAuditLog(
                    id=str(uuid4()), organization_id=scope["organization_id"], conversation_id=scope["conversation_id"],
                    action="m314.concurrent_consumer.side_effect", actor_type="system", details=consumer_label,
                ))
            results.put(consume_event(db, organization_id=scope["organization_id"], event_id=event_id, consumer_name="m314-concurrent", handler=side_effect))
        finally:
            db.close()

    first, second = Thread(target=consume, args=("consumer-a",)), Thread(target=consume, args=("consumer-b",))
    first.start(); second.start(); first.join(timeout=15); second.join(timeout=15)
    assert not first.is_alive() and not second.is_alive()
    assert sorted([results.get_nowait(), results.get_nowait()]) == [False, True]

    # Independent session proves the unique ledger prevented a duplicate durable side effect.
    with SessionLocal() as verification:
        assert verification.query(WorkflowEventConsumption).filter_by(organization_id=scope["organization_id"], event_id=event_id, consumer_name="m314-concurrent").count() == 1
        assert verification.query(ConversationAuditLog).filter_by(organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], action="m314.concurrent_consumer.side_effect").count() == 1


def test_m314_redis_outage_restart_recovery_preserves_outbox_and_deduplicates(mysql_supervisor_scope) -> None:
    """A fault-injected Redis outage leaves MySQL durable; restart/reclaim is safe."""
    scope = mysql_supervisor_scope
    event_id = _new_outbox_event(scope, "redis-restart")
    stream, group = f"had:test:m314:restart:{uuid4()}", "m314-restart"

    class OutageRedis:
        def xadd(self, *_args, **_kwargs):
            raise RuntimeError("simulated Redis outage; no connection details retained")

    redis = get_redis_client()
    try:
        # First dispatcher instance claims then fails to publish without touching Redis.
        with SessionLocal() as first_dispatcher:
            assert [row.id for row in lease_events(first_dispatcher, publisher_id="m314-dispatcher-before", limit=1, lease_seconds=1)] == [event_id]
            assert not publish_leased_event(first_dispatcher, event_id=event_id, publisher_id="m314-dispatcher-before", redis_client=OutageRedis(), stream=stream)

        with SessionLocal() as after_outage:
            event = after_outage.get(WorkflowOutboxEvent, event_id)
            assert event.status == "pending" and event.attempt_count == 1 and event.next_attempt_at is not None
            assert event.last_error_code == "REDIS_PUBLISH_FAILED"
            assert event.last_error_message == "Redis stream publish failed."
            assert after_outage.query(ConversationAuditLog).filter_by(organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], action="outbox.publish_failed").count() == 1
            # Make the retry due; this represents a dispatcher process returning after downtime.
            event.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            after_outage.commit()

        # A restarted dispatcher obtains a new lease and delivers to an isolated stream.
        with SessionLocal() as restarted_dispatcher:
            assert [row.id for row in lease_events(restarted_dispatcher, publisher_id="m314-dispatcher-after", limit=1, lease_seconds=1)] == [event_id]
            assert publish_leased_event(restarted_dispatcher, event_id=event_id, publisher_id="m314-dispatcher-after", redis_client=redis, stream=stream)

        redis.xgroup_create(stream, group, id="0-0", mkstream=True)
        delivered = redis.xreadgroup(group, "consumer-crashed", {stream: ">"}, count=1, block=1000)
        entry_id = delivered[0][1][0][0]
        reclaimed = reclaim_pending_entries(redis, stream=stream, group=group, consumer="consumer-restarted", min_idle_ms=0)
        assert any(item[0] == entry_id for item in reclaimed)

        def side_effect(db: Session, _event: WorkflowOutboxEvent) -> None:
            db.add(ConversationAuditLog(
                id=str(uuid4()), organization_id=scope["organization_id"], conversation_id=scope["conversation_id"],
                action="m314.redis_restart.side_effect", actor_type="system",
            ))

        with SessionLocal() as first_consumer:
            assert consume_event(first_consumer, organization_id=scope["organization_id"], event_id=event_id, consumer_name="m314-redis-restart", handler=side_effect)

        # Commit has happened; acknowledgement fails, so another restarted consumer must reclaim and deduplicate.
        class FailingXack:
            def xack(self, *_args, **_kwargs):
                raise RuntimeError("simulated XACK outage")
        with pytest.raises(RuntimeError, match="simulated XACK outage"):
            ack_after_commit(FailingXack(), stream=stream, group=group, entry_id=entry_id)
        assert any(item[0] == entry_id for item in reclaim_pending_entries(redis, stream=stream, group=group, consumer="consumer-after-restart", min_idle_ms=0))
        with SessionLocal() as replay_consumer:
            assert not consume_event(replay_consumer, organization_id=scope["organization_id"], event_id=event_id, consumer_name="m314-redis-restart", handler=side_effect)
        ack_after_commit(redis, stream=stream, group=group, entry_id=entry_id)

        # Independent MySQL verification of retry count, final event state, and exactly-once durable effects.
        with SessionLocal() as verification:
            event = verification.get(WorkflowOutboxEvent, event_id)
            assert event.status == "published" and event.attempt_count == 2
            assert verification.query(WorkflowEventConsumption).filter_by(organization_id=scope["organization_id"], event_id=event_id, consumer_name="m314-redis-restart").count() == 1
            assert verification.query(ConversationAuditLog).filter_by(organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], action="m314.redis_restart.side_effect").count() == 1
    finally:
        redis.delete(stream)


def test_m314_supervisor_rejects_cross_project_and_unpublished_agent(mysql_supervisor_scope) -> None:
    """Eligibility is project-scoped and requires a published agent version on MySQL."""
    scope = mysql_supervisor_scope
    other_conversation_id = str(uuid4())
    with SessionLocal() as setup:
        setup.add(Conversation(
            id=other_conversation_id, organization_id=scope["organization_id"], project_id=scope["other_project_id"],
            created_by_user_id=scope["user_id"], title="M314 other project", status="active",
        ))
        setup.flush()
        setup.add(ConversationMember(
            id=str(uuid4()), organization_id=scope["organization_id"], conversation_id=other_conversation_id,
            member_type="user", user_id=scope["user_id"], membership_role="owner",
        ))
        setup.commit()

    with SessionLocal() as cross_project:
        with pytest.raises(PlanValidationError, match="active and assigned"):
            create_plan(cross_project, organization_id=scope["organization_id"], conversation_id=other_conversation_id,
                        actor_user_id=scope["user_id"], goal="cross project", strategy="sequential", tasks=_plan_task(scope, "reporting"))

    with SessionLocal() as unpublish:
        version = unpublish.query(AgentVersion).filter_by(organization_id=scope["organization_id"], agent_profile_id=scope["agent_id"]).one()
        version.is_published = False
        unpublish.commit()
    with SessionLocal() as unpublished:
        with pytest.raises(RuntimeValidationError, match="No published version"):
            create_plan(unpublished, organization_id=scope["organization_id"], conversation_id=scope["conversation_id"],
                        actor_user_id=scope["user_id"], goal="unpublished", strategy="sequential", tasks=_plan_task(scope, "reporting"))

    with SessionLocal() as verification:
        assert verification.query(SupervisorPlan).filter_by(organization_id=scope["organization_id"]).count() == 0
        assert verification.query(ConversationTask).filter_by(organization_id=scope["organization_id"]).count() == 0
        assert verification.query(AgentExecution).filter_by(organization_id=scope["organization_id"]).count() == 0


def test_m314_end_to_end_conversation_supervisor_approval_outbox_workflow(mysql_supervisor_scope) -> None:
    """Conversation → plan → runtime → M2.5 approval → durable outbox, all persisted."""
    scope = mysql_supervisor_scope
    with SessionLocal() as workflow:
        message = append_user_message(
            workflow, organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], user_id=scope["user_id"],
            content="patient_id=P-M314-001; prepare clinical triage", idempotency_key=f"m314-e2e-message:{uuid4()}", expected_state_version=1,
        )
        plan = create_plan(
            workflow, organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], actor_user_id=scope["user_id"],
            goal="M314 end-to-end", strategy="sequential", tasks=_plan_task(scope, "clinical_triage"),
        )
        task = workflow.query(ConversationTask).filter_by(organization_id=scope["organization_id"], conversation_id=scope["conversation_id"]).one()
        approval = workflow.query(AgentExecutionApproval).filter_by(organization_id=scope["organization_id"], execution_id=task.execution_id, status="pending").one()
        assert message.content_redacted != "patient_id=P-M314-001; prepare clinical triage"
        assert task.status == "waiting_approval"
        review_execution_approval(workflow, organization_id=scope["organization_id"], approval_id=approval.id, reviewer_user_id=scope["reviewer_a_id"], status="approved", comment="M314 authorized review")
        plan_id, task_id, execution_id, approval_id = plan.id, task.id, task.execution_id, approval.id

    # Independent session proves each workflow stage is durable and consistent.
    with SessionLocal() as verification:
        conversation = verification.get(Conversation, scope["conversation_id"])
        task = verification.get(ConversationTask, task_id)
        execution = verification.get(AgentExecution, execution_id)
        approval = verification.get(AgentExecutionApproval, approval_id)
        plan = verification.get(SupervisorPlan, plan_id)
        outbox = verification.query(WorkflowOutboxEvent).filter_by(organization_id=scope["organization_id"], conversation_id=scope["conversation_id"], event_type="conversation.message_created").one()
        assert conversation.state_version == 2 and plan.status == "validated"
        assert task.status == "queued" and execution.status == "queued"
        assert approval.status == "approved" and approval.reviewer_user_id == scope["reviewer_a_id"]
        assert outbox.aggregate_id == scope["conversation_id"] and "P-M314-001" not in outbox.payload
