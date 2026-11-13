"""Offline checks that the M3.2.2 package exposes one normative routing contract.

These checks deliberately inspect documentation only.  They neither start a
worker nor connect to Redis, MySQL, Alembic, Docker, LLM providers, or tools.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "docs/M3.2.2_AGENT_TO_AGENT_EVENT_ROUTING_ARCHITECTURE_AND_IMPLEMENTATION_PACKAGE.md"


def _package() -> str:
    return PACKAGE.read_text(encoding="utf-8")


def test_revision_one_conformance_makes_one_topology_normative():
    source = _package()
    assert "Revision 1 conformance:" in source
    assert "one trusted-router topology" in source
    assert "The router is the only consumer group permitted to acknowledge this stream." in source


def test_ledger_and_workflow_ordering_are_not_process_or_timeline_owned():
    source = _package()
    assert "(organization_id, workflow_outbox_event_id, logical_handler_id)" in source
    assert "`redis_consumer_id` is unique per live worker process" in source
    assert "timeline order. It is not an actionable dependency watermark" in source
    assert "(organization_id, conversation_id, workflow_version, transition_key)" in source


def test_router_cannot_become_an_approval_or_external_effect_bypass():
    source = _package()
    assert "Routing creates local intent only; Runtime owns external effects" in source
    assert "M2.5 remains the only policy and human-approval authority." in source
    assert "workers remain disabled" in source
