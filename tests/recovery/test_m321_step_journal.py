"""Offline tests for M3.2.1's review-only lock/PREPARED journal contract."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/recovery/m321_step_journal.py"
spec = importlib.util.spec_from_file_location("m321_step_journal", SOURCE)
assert spec and spec.loader
j = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = j
spec.loader.exec_module(j)

HASH_A, HASH_B, HASH_C = "a" * 64, "b" * 64, "c" * 64
OWNER_A = {"epoch": 1, "instance_id": "writer-a", "run_nonce": "nonce-a"}
OWNER_B = {"epoch": 2, "instance_id": "writer-b", "run_nonce": "nonce-b"}


def _journal():
    return j.new_journal(rehearsal_id="review-only-fixture", sql_sha256=HASH_A)


def _observed(label: str, passed: bool = True):
    return [{"check": label, "expected": "expected", "observed": "actual", "passed": passed}]


def _prepare_kwargs(step_id: str | None = None):
    return {
        "step_id": step_id or str(uuid4()), "statement": "ALTER TABLE review_only",
        "preconditions": ["reviewed precondition"],
        "observed_preconditions": _observed("precondition"),
        "before_schema_snapshot_sha256": HASH_A,
        "disposable_target_identity": {"database": "had_m321_a2_fixture", "host": "127.0.0.1", "port": 34071},
        "operator_approval_reference": "independent-review-required",
        "ownership": copy.deepcopy(OWNER_A),
    }


def _pass_kwargs(step_id: str):
    return {
        "prepared_step_id": step_id, "postconditions": ["reviewed postcondition"],
        "observed_postconditions": _observed("postcondition"), "after_schema_snapshot_sha256": HASH_B,
        "ownership": copy.deepcopy(OWNER_A),
    }


def _reconciliation_authorization(step_id: str, prior_ownership: dict):
    return {
        "approved": True,
        "approval_reference": "independent-reconciliation-review-001",
        "reviewer_id": "reviewer-not-runner",
        "evidence_sha256": HASH_C,
        "prepared_step_id": step_id,
        "prior_ownership": copy.deepcopy(prior_ownership),
    }


class _HeldLock:
    def __init__(self, path, *, rehearsal_id, instance_id="fixture", run_nonce="fixture"):
        self.path, self.rehearsal_id, self.held = path, rehearsal_id, False

    def acquire(self):
        self.held = True
        return self

    def release(self):
        self.held = False

    def is_held_for(self, path, rehearsal_id):
        return self.held and path == self.path and rehearsal_id == self.rehearsal_id


class _ContendedLock(_HeldLock):
    active = False

    def acquire(self):
        if type(self).active:
            raise j.JournalViolation("Journal lock contention")
        type(self).active = True
        return super().acquire()

    def release(self):
        type(self).active = False
        super().release()


def _memory_persistence(monkeypatch):
    stored = {}
    monkeypatch.setattr(Path, "exists", lambda self: "journal" in stored)
    monkeypatch.setattr(j, "_atomic_write_bytes", lambda _path, content: stored.update(journal=json.loads(content.decode("utf-8"))))
    monkeypatch.setattr(j, "load_journal", lambda _path: copy.deepcopy(stored["journal"]))
    return stored


def test_prepared_then_passed_records_fingerprints_observations_and_snapshots():
    state = _journal()
    prepared = j.prepare_step(state, **_prepare_kwargs())
    assert state["status"] == j.PREPARED
    outcome = j.record_pass(state, **_pass_kwargs(prepared["step_id"]))
    assert state["status"] == j.IN_PROGRESS_REVIEW_ONLY
    assert outcome["status"] == j.PASSED
    assert outcome["statement_sha256"] == prepared["statement_sha256"]
    assert outcome["after_schema_snapshot_sha256"] == HASH_B


@pytest.mark.parametrize("field", ["observed_preconditions", "observed_postconditions"])
def test_failed_observation_cannot_become_passed(field):
    state = _journal()
    prepared = j.prepare_step(state, **_prepare_kwargs())
    kwargs = _pass_kwargs(prepared["step_id"])
    if field == "observed_preconditions":
        other = _journal()
        bad = _prepare_kwargs()
        bad[field] = _observed(field, False)
        with pytest.raises(j.JournalViolation, match="failed assertion"):
            j.prepare_step(other, **bad)
    else:
        kwargs[field] = _observed(field, False)
        with pytest.raises(j.JournalViolation, match="failed assertion"):
            j.record_pass(state, **kwargs)


def test_pass_without_persisted_prepared_record_is_refused():
    with pytest.raises(j.JournalViolation, match="PREPARED"):
        j.record_pass(_journal(), **_pass_kwargs(str(uuid4())))


def test_terminal_stop_is_only_valid_outcome_for_prepared_step():
    state = _journal()
    prepared = j.prepare_step(state, **_prepare_kwargs())
    terminal = j.stop_no_retry(
        state, prepared_step_id=prepared["step_id"], observed_postconditions=_observed("failure", False),
        after_schema_snapshot_sha256=HASH_C, exit_code=2, reason_code="POSTCONDITION_FAILED",
        ownership=copy.deepcopy(OWNER_A),
    )
    assert terminal["retry_permitted"] is False
    assert state["status"] == j.STOP_NO_RETRY
    with pytest.raises(j.JournalViolation):
        j.prepare_step(state, **_prepare_kwargs())


def test_tampered_prepared_record_fails_integrity_verification():
    state = _journal()
    j.prepare_step(state, **_prepare_kwargs())
    sealed = j.seal_journal(state)
    sealed["steps"][0]["operator_approval_reference"] = "forged"
    with pytest.raises(j.JournalViolation, match="integrity"):
        j.verify_integrity(sealed)


def test_persistence_revalidates_forged_failed_passed_observation(monkeypatch):
    stored = _memory_persistence(monkeypatch)
    path, lock, state = Path("review-only-journal.json"), _HeldLock(Path("review-only-journal.json"), rehearsal_id="review-only-fixture"), _journal()
    lock.acquire()
    prepared = j.prepare_step(state, **_prepare_kwargs())
    j.write_journal(path, state, lock=lock)
    j.record_pass(state, **_pass_kwargs(prepared["step_id"]))
    state["steps"][-1]["observed_postconditions"][0]["passed"] = False
    with pytest.raises(j.JournalViolation, match="failed assertion"):
        j.write_journal(path, state, lock=lock)
    assert stored["journal"]["status"] == j.PREPARED


def test_in_progress_without_completed_prepared_step_is_refused(monkeypatch):
    _memory_persistence(monkeypatch)
    state = _journal()
    state["status"] = j.IN_PROGRESS_REVIEW_ONLY
    lock = _HeldLock(Path("review-only-journal.json"), rehearsal_id="review-only-fixture").acquire()
    with pytest.raises(j.JournalViolation, match="In-progress"):
        j.write_journal(Path("review-only-journal.json"), state, lock=lock)


def test_persistence_requires_matching_held_lock(monkeypatch):
    _memory_persistence(monkeypatch)
    with pytest.raises(j.JournalViolation, match="held matching"):
        j.write_journal(Path("review-only-journal.json"), _journal(), lock=_HeldLock(Path("other.json"), rehearsal_id="wrong"))


def test_append_only_rejects_metadata_and_status_mutation():
    state = _journal()
    prepared = j.prepare_step(state, **_prepare_kwargs())
    j.record_pass(state, **_pass_kwargs(prepared["step_id"]))
    persisted = j.seal_journal(state)
    for field, value in (("status", j.PENDING_REVIEW), ("created_at_utc", "forged"), ("schema_version", 999)):
        candidate = copy.deepcopy(persisted)
        candidate.pop("integrity")
        candidate[field] = value
        with pytest.raises(j.JournalViolation):
            j._assert_append_only(persisted, j.seal_journal(candidate))


def test_second_writer_is_refused_while_first_mutation_holds_lock(monkeypatch):
    _memory_persistence(monkeypatch)
    _ContendedLock.active = False
    path, initial = Path("review-only-journal.json"), _journal()
    with j.JournalMutation(path, initial, instance_id="writer-a", run_nonce="nonce-a", lock_factory=_ContendedLock):
        with pytest.raises(j.JournalViolation, match="contention"):
            with j.JournalMutation(path, initial, instance_id="writer-b", run_nonce="nonce-b", lock_factory=_ContendedLock):
                pass


def test_unresolved_prepared_blocks_another_prepare_and_requires_manual_review():
    state = _journal()
    j.prepare_step(state, **_prepare_kwargs())
    with pytest.raises(j.JournalViolation, match="cannot prepare"):
        j.prepare_step(state, **_prepare_kwargs())
    sealed = j.seal_journal(state)
    j._validate_journal_state(sealed)


def test_journal_mutation_persists_prepared_before_outcome(monkeypatch):
    stored = _memory_persistence(monkeypatch)
    path, state = Path("review-only-journal.json"), _journal()
    with j.JournalMutation(path, state, instance_id="writer-a", run_nonce="nonce-a", lock_factory=_HeldLock) as mutation:
        prepared_journal = mutation.prepare_and_persist(**_prepare_kwargs())
        prepared_id = prepared_journal["steps"][-1]["step_id"]
        assert stored["journal"]["status"] == j.PREPARED
        mutation.pass_and_persist(**_pass_kwargs(prepared_id))
    assert stored["journal"]["status"] == j.IN_PROGRESS_REVIEW_ONLY


def test_first_durable_write_rejects_batched_prepared_and_passed(monkeypatch):
    _memory_persistence(monkeypatch)
    state = _journal()
    prepared = j.prepare_step(state, **_prepare_kwargs())
    j.record_pass(state, **_pass_kwargs(prepared["step_id"]))
    path = Path("review-only-journal.json")
    lock = _HeldLock(path, rehearsal_id="review-only-fixture").acquire()
    with pytest.raises(j.JournalViolation, match="First durable write"):
        j.write_journal(path, state, lock=lock)


def test_persistence_failure_latches_session_and_keeps_original_state(monkeypatch):
    _memory_persistence(monkeypatch)
    path, initial = Path("review-only-journal.json"), _journal()
    with j.JournalMutation(path, initial, instance_id="writer-a", run_nonce="nonce-a", lock_factory=_HeldLock) as mutation:
        monkeypatch.setattr(j, "write_journal", lambda *_args, **_kwargs: (_ for _ in ()).throw(j.JournalViolation("injected write failure")))
        with pytest.raises(j.JournalViolation, match="injected"):
            mutation.prepare_and_persist(**_prepare_kwargs())
        assert mutation.journal is not None
        assert mutation.journal["status"] == j.PENDING_REVIEW
        with pytest.raises(j.JournalViolation, match="fault-latched"):
            mutation.prepare_and_persist(**_prepare_kwargs())


def test_enter_failure_releases_lock(monkeypatch):
    lock = _HeldLock(Path("review-only-journal.json"), rehearsal_id="review-only-fixture")
    mutation = j.JournalMutation(
        Path("review-only-journal.json"), _journal(), instance_id="writer-a", run_nonce="nonce-a",
        lock_factory=lambda *_args, **_kwargs: lock,
    )
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(j, "load_journal", lambda _path: (_ for _ in ()).throw(j.JournalViolation("malformed journal")))
    with pytest.raises(j.JournalViolation, match="malformed"):
        mutation.__enter__()
    assert lock.held is False


def test_orphaned_prepared_requires_authorized_reconciliation_before_outcome(monkeypatch):
    stored = _memory_persistence(monkeypatch)
    path, initial = Path("review-only-journal.json"), _journal()
    with j.JournalMutation(path, initial, instance_id="writer-a", run_nonce="nonce-a", lock_factory=_HeldLock) as writer_a:
        writer_a.prepare_and_persist(**_prepare_kwargs())
        prepared_id = writer_a.journal["steps"][-1]["step_id"]
        prior_ownership = copy.deepcopy(writer_a.journal["steps"][-1]["ownership"])

    with j.JournalMutation(path, initial, instance_id="writer-b", run_nonce="nonce-b", lock_factory=_HeldLock) as writer_b:
        with pytest.raises(j.JournalViolation, match="Orphaned PREPARED"):
            writer_b.pass_and_persist(**_pass_kwargs(prepared_id))
    with j.JournalMutation(path, initial, instance_id="writer-b", run_nonce="nonce-b", lock_factory=_HeldLock) as writer_b:
        with pytest.raises(j.JournalViolation, match="unapproved"):
            writer_b.reconcile_prepared_and_persist(
                reconciliation_authorization={"approved": False},
                observed_reconciliation=_observed("reviewed orphan state"),
            )
    with j.JournalMutation(path, initial, instance_id="writer-b", run_nonce="nonce-b", lock_factory=_HeldLock) as writer_b:
        reconciled = writer_b.reconcile_prepared_and_persist(
            reconciliation_authorization=_reconciliation_authorization(prepared_id, prior_ownership),
            observed_reconciliation=_observed("reviewed orphan state"),
        )
        assert reconciled["status"] == j.RECONCILIATION_APPROVED
        writer_b.pass_and_persist(**_pass_kwargs(prepared_id))

    assert [record["status"] for record in stored["journal"]["steps"]] == [j.PREPARED, j.RECONCILED, j.PASSED]
    assert stored["journal"]["steps"][1]["prior_ownership"] == OWNER_A
    assert stored["journal"]["steps"][2]["ownership"] == OWNER_B


def test_reconciliation_rejects_wrong_prior_owner_or_step():
    state = _journal()
    prepared = j.prepare_step(state, **_prepare_kwargs())
    authorization = _reconciliation_authorization(prepared["step_id"], OWNER_A)
    authorization["prior_ownership"] = copy.deepcopy(OWNER_B)
    with pytest.raises(j.JournalViolation, match="ownership"):
        j.reconcile_prepared(
            state,
            reconciliation_authorization=authorization,
            observed_reconciliation=_observed("reviewed orphan state"),
            ownership=copy.deepcopy(OWNER_B),
        )


def test_windows_lock_uses_fixed_byte_file_and_metadata_sidecar_not_append_mode():
    source = SOURCE.read_text(encoding="utf-8")
    assert 'open("a+b")' not in source
    assert 'open("x+b")' in source
    assert 'open("r+b")' in source
    assert ".lock.meta" in source


def test_windows_lock_byte_and_json_sidecar_are_separate_in_simulation(monkeypatch):
    class FakeHandle:
        def __init__(self):
            self.writes = []
            self.positions = []

        def seek(self, position):
            self.positions.append(position)

        def write(self, value):
            self.writes.append(value)

        def flush(self):
            pass

        def fileno(self):
            return 73

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2
        calls = []

        @classmethod
        def locking(cls, descriptor, operation, length):
            cls.calls.append((descriptor, operation, length))

    writes = {}
    lock = j.JournalFileLock(Path("review-only-journal.json"), rehearsal_id="review-only-fixture", instance_id="writer-a", run_nonce="nonce-a")
    monkeypatch.setattr(j.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt)
    monkeypatch.setattr(j, "_atomic_write_bytes", lambda path, content: writes.setdefault(path, content))
    handle = FakeHandle()
    lock._lock_os_handle(handle)
    lock._write_metadata("held")

    assert handle.writes == [b"\0"]
    assert handle.positions == [0]
    assert FakeMsvcrt.calls == [(73, FakeMsvcrt.LK_NBLCK, 1)]
    assert lock.metadata_path != lock.lock_path
    assert writes[lock.metadata_path].startswith(b"{")
    assert b"\0" not in writes[lock.metadata_path]
