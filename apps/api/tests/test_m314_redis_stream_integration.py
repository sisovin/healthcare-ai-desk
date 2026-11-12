"""M3.1.4 Redis fault/recovery evidence using an isolated, disposable stream."""

from uuid import uuid4

from app.core.dependencies import get_redis_client
from app.services.outbox_service import ack_after_commit, reclaim_pending_entries


def test_real_redis_stream_ack_duplicate_and_pending_reclaim() -> None:
    redis = get_redis_client()
    stream = f"had:test:m314:{uuid4()}"
    group = "m314-test-group"
    try:
        redis.xgroup_create(stream, group, id="0-0", mkstream=True)
        entry_id = redis.xadd(stream, {"event_id": "outbox-1", "idempotency_key": "m314-1"})
        delivered = redis.xreadgroup(group, "worker-a", {stream: ">"}, count=1, block=1000)
        assert delivered and delivered[0][1][0][0] == entry_id

        # A duplicate is harmless at the consumer layer; acknowledgement happens
        # only after its database idempotency transaction succeeds.
        ack_after_commit(redis, stream=stream, group=group, entry_id=entry_id)
        assert redis.xpending_range(stream, group, "-", "+", 10) == []

        pending_id = redis.xadd(stream, {"event_id": "outbox-2", "idempotency_key": "m314-2"})
        redis.xreadgroup(group, "worker-crashed", {stream: ">"}, count=1, block=1000)
        reclaimed = reclaim_pending_entries(redis, stream=stream, group=group, consumer="worker-recovery", min_idle_ms=0)
        assert any(entry[0] == pending_id for entry in reclaimed)
        ack_after_commit(redis, stream=stream, group=group, entry_id=pending_id)
    finally:
        redis.delete(stream)
