"""Review-only M3.2.1 Phase A.2 journal integrity primitives.

This module is deliberately not an SQL, Alembic, Docker, or database runner.
It provides the durable-journal contract a separately authorized future runner
must use: exclusive journal ownership, persisted PREPARED evidence before a
statement, independently authorized orphan reconciliation, append-only
outcomes, and terminal STOP_NO_RETRY evidence.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 4
PENDING_REVIEW = "PENDING_REVIEW"
PREPARED = "PREPARED"
IN_PROGRESS_REVIEW_ONLY = "IN_PROGRESS_REVIEW_ONLY"
RECONCILIATION_APPROVED = "RECONCILIATION_APPROVED"
RECONCILED = "RECONCILED"
PASSED = "PASSED"
STOP_NO_RETRY = "STOP_NO_RETRY"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MUTABLE_FIELDS = {"steps", "status", "terminal_record", "integrity"}
_LEGAL_TRANSITIONS = {
    PENDING_REVIEW: {PENDING_REVIEW, PREPARED},
    PREPARED: {PREPARED, RECONCILIATION_APPROVED, IN_PROGRESS_REVIEW_ONLY, STOP_NO_RETRY},
    RECONCILIATION_APPROVED: {RECONCILIATION_APPROVED, IN_PROGRESS_REVIEW_ONLY, STOP_NO_RETRY},
    IN_PROGRESS_REVIEW_ONLY: {IN_PROGRESS_REVIEW_ONLY, PREPARED},
    STOP_NO_RETRY: {STOP_NO_RETRY},
}


class JournalViolation(RuntimeError):
    """Fail-closed journal integrity, ownership, or persistence violation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def statement_fingerprint(statement: str) -> str:
    if not isinstance(statement, str) or not statement.strip():
        raise JournalViolation("Statement must be non-empty")
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError):
        raise JournalViolation("Journal contains non-JSON evidence") from None


def _without_integrity(journal: dict[str, Any]) -> dict[str, Any]:
    copy_of_journal = copy.deepcopy(journal)
    copy_of_journal.pop("integrity", None)
    return copy_of_journal


def _require_sha256(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise JournalViolation(f"{label} must be a SHA-256 hash")


def _require_uuid(value: Any, label: str) -> None:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise JournalViolation(f"{label} must be a UUID") from None


def _validate_observed(items: Any, label: str, *, all_passed: bool = False) -> None:
    if not isinstance(items, list) or not items:
        raise JournalViolation(f"{label} must be a non-empty observed-assertion list")
    for item in items:
        if not isinstance(item, dict) or {"check", "expected", "observed", "passed"} - set(item):
            raise JournalViolation(f"{label} assertion fields are incomplete")
        if not isinstance(item["check"], str) or not item["check"] or not isinstance(item["passed"], bool):
            raise JournalViolation(f"{label} assertion is invalid")
        if all_passed and item["passed"] is not True:
            raise JournalViolation(f"{label} contains a failed assertion; continuation is forbidden")


def _validate_ownership(value: Any, label: str) -> None:
    """Validate the immutable ownership epoch for a prepared/reconciled step."""
    if not isinstance(value, dict) or set(value) != {"epoch", "instance_id", "run_nonce"}:
        raise JournalViolation(f"{label} ownership evidence is incomplete")
    epoch = value.get("epoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
        raise JournalViolation(f"{label} ownership epoch is invalid")
    for field in ("instance_id", "run_nonce"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise JournalViolation(f"{label} ownership identity is invalid")


def _same_ownership(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left == right


def _latest_ownership_epoch(journal: dict[str, Any]) -> int:
    epochs = [
        record["ownership"]["epoch"]
        for record in journal["steps"]
        if record.get("status") in {PREPARED, RECONCILED} and isinstance(record.get("ownership"), dict)
    ]
    return max(epochs, default=0)


def _validate_base(journal: Any) -> None:
    if not isinstance(journal, dict):
        raise JournalViolation("Journal must be an object")
    if journal.get("schema_version") != SCHEMA_VERSION or journal.get("milestone") != "M3.2.1 Phase A.2":
        raise JournalViolation("Journal schema or milestone is invalid")
    if journal.get("execution_authorization") is not False or journal.get("review_only") is not True:
        raise JournalViolation("Journal must remain review-only and unauthorized")
    if not isinstance(journal.get("rehearsal_id"), str) or not journal["rehearsal_id"]:
        raise JournalViolation("Journal rehearsal identity is invalid")
    _require_sha256(journal.get("reviewed_sql_sha256"), "Reviewed SQL")
    if not isinstance(journal.get("steps"), list):
        raise JournalViolation("Journal steps must be a list")


def seal_journal(journal: dict[str, Any]) -> dict[str, Any]:
    _validate_base(journal)
    sealed = _without_integrity(journal)
    sealed["integrity"] = {
        "algorithm": "sha256",
        "content_sha256": hashlib.sha256(_canonical_bytes(sealed)).hexdigest(),
    }
    return sealed


def verify_integrity(journal: dict[str, Any]) -> None:
    _validate_base(journal)
    integrity = journal.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        raise JournalViolation("Journal integrity metadata is missing or unsupported")
    expected = integrity.get("content_sha256")
    _require_sha256(expected, "Journal integrity")
    actual = hashlib.sha256(_canonical_bytes(_without_integrity(journal))).hexdigest()
    if not hmac.compare_digest(expected, actual):
        raise JournalViolation("Journal integrity verification failed")


def new_journal(*, rehearsal_id: str, sql_sha256: str) -> dict[str, Any]:
    if not rehearsal_id:
        raise JournalViolation("A rehearsal identifier is required")
    _require_sha256(sql_sha256, "Reviewed SQL")
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M3.2.1 Phase A.2",
        "rehearsal_id": rehearsal_id,
        "created_at_utc": utc_now(),
        "execution_authorization": False,
        "review_only": True,
        "reviewed_sql_sha256": sql_sha256,
        "status": PENDING_REVIEW,
        "steps": [],
        "terminal_record": None,
    }


def _open_prepared(journal: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    _validate_journal_state(journal)
    if journal["status"] == PREPARED and journal["steps"] and journal["steps"][-1]["status"] == PREPARED:
        return journal["steps"][-1], journal["steps"][-1]["ownership"]
    if journal["status"] == RECONCILIATION_APPROVED and len(journal["steps"]) >= 2:
        prepared, reconciliation = journal["steps"][-2:]
        if prepared["status"] == PREPARED and reconciliation["status"] == RECONCILED:
            return prepared, reconciliation["ownership"]
    raise JournalViolation("A persisted PREPARED record is required before an outcome")


def _validate_reconciliation_authorization(
    authorization: Any, *, prepared_step_id: str, prior_ownership: dict[str, Any],
) -> None:
    """Require a structured, independently reviewed reconciliation reference.

    The journal cannot prove an external approval was valid.  It can, however,
    fail closed unless a separately supplied approval ties the exact orphaned
    PREPARED step and ownership epoch to immutable review evidence.
    """
    if not isinstance(authorization, dict):
        raise JournalViolation("Reconciliation authorization is required")
    required = {
        "approved", "approval_reference", "reviewer_id", "evidence_sha256",
        "prepared_step_id", "prior_ownership",
    }
    if set(authorization) != required or authorization.get("approved") is not True:
        raise JournalViolation("Reconciliation authorization is incomplete or unapproved")
    if authorization.get("prepared_step_id") != prepared_step_id:
        raise JournalViolation("Reconciliation authorization targets another prepared step")
    if authorization.get("prior_ownership") != prior_ownership:
        raise JournalViolation("Reconciliation authorization ownership does not match")
    if not isinstance(authorization.get("approval_reference"), str) or not authorization["approval_reference"]:
        raise JournalViolation("Reconciliation approval reference is invalid")
    if not isinstance(authorization.get("reviewer_id"), str) or not authorization["reviewer_id"]:
        raise JournalViolation("Reconciliation reviewer identity is invalid")
    _require_sha256(authorization.get("evidence_sha256"), "Reconciliation evidence")


def _validate_reconciliation_record(record: dict[str, Any], prepared: dict[str, Any]) -> None:
    if record.get("prepared_step_id") != prepared.get("step_id") or record.get("step_id") != prepared.get("step_id"):
        raise JournalViolation("Reconciliation does not match the unresolved PREPARED step")
    if record.get("statement_sha256") != prepared.get("statement_sha256"):
        raise JournalViolation("Reconciliation statement does not match PREPARED evidence")
    prior = record.get("prior_ownership")
    if prior != prepared.get("ownership"):
        raise JournalViolation("Reconciliation prior ownership does not match PREPARED evidence")
    _validate_ownership(record.get("ownership"), "Reconciliation")
    if _same_ownership(record["ownership"], prior):
        raise JournalViolation("Reconciliation must establish a new ownership epoch")
    _validate_reconciliation_authorization(
        record.get("reconciliation_authorization"),
        prepared_step_id=prepared["step_id"],
        prior_ownership=prior,
    )
    _validate_observed(record.get("observed_reconciliation"), "Observed reconciliation", all_passed=True)


def _outcome_prepared_and_owner(journal: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return _open_prepared(journal)
    except JournalViolation:
        raise JournalViolation("A persisted PREPARED record is required before an outcome")


def prepare_step(
    journal: dict[str, Any], *, step_id: str, statement: str, preconditions: list[str],
    observed_preconditions: list[dict[str, Any]], before_schema_snapshot_sha256: str,
    disposable_target_identity: dict[str, Any], operator_approval_reference: str,
    ownership: dict[str, Any],
) -> dict[str, Any]:
    """Append PREPARED evidence before a separately authorized future statement."""
    _validate_journal_state(journal)
    if journal["status"] not in {PENDING_REVIEW, IN_PROGRESS_REVIEW_ONLY}:
        raise JournalViolation("Journal cannot prepare another statement in its current state")
    _require_uuid(step_id, "Prepared step ID")
    if not isinstance(preconditions, list) or not isinstance(disposable_target_identity, dict) or not disposable_target_identity:
        raise JournalViolation("Prepared preconditions and target identity are required")
    if not isinstance(operator_approval_reference, str) or not operator_approval_reference:
        raise JournalViolation("Prepared step requires an approval reference")
    _validate_observed(observed_preconditions, "Prepared observed preconditions", all_passed=True)
    _require_sha256(before_schema_snapshot_sha256, "Prepared before snapshot")
    _validate_ownership(ownership, "Prepared")
    record = {
        "recorded_at_utc": utc_now(), "status": PREPARED, "step_id": step_id,
        "statement_sha256": statement_fingerprint(statement), "preconditions": preconditions,
        "observed_preconditions": observed_preconditions,
        "before_schema_snapshot_sha256": before_schema_snapshot_sha256,
        "disposable_target_identity": disposable_target_identity,
        "operator_approval_reference": operator_approval_reference,
        "ownership": copy.deepcopy(ownership),
    }
    journal["steps"].append(record)
    journal["status"] = PREPARED
    return record


def record_pass(
    journal: dict[str, Any], *, prepared_step_id: str, postconditions: list[str],
    observed_postconditions: list[dict[str, Any]], after_schema_snapshot_sha256: str,
    ownership: dict[str, Any],
) -> dict[str, Any]:
    """Append a verified PASSED outcome for the immediately preceding PREPARED step."""
    prepared, effective_owner = _outcome_prepared_and_owner(journal)
    _require_uuid(prepared_step_id, "Prepared step ID")
    if prepared["step_id"] != prepared_step_id:
        raise JournalViolation("Outcome does not match the unresolved PREPARED step")
    if not isinstance(postconditions, list):
        raise JournalViolation("Postconditions are required")
    _validate_observed(observed_postconditions, "Observed postconditions", all_passed=True)
    _require_sha256(after_schema_snapshot_sha256, "After schema snapshot")
    _validate_ownership(ownership, "Outcome")
    if not _same_ownership(ownership, effective_owner):
        raise JournalViolation("Outcome ownership does not match the authorized PREPARED epoch")
    record = {
        "recorded_at_utc": utc_now(), "status": PASSED, "step_id": prepared_step_id,
        "prepared_step_id": prepared_step_id, "statement_sha256": prepared["statement_sha256"],
        "postconditions": postconditions, "observed_postconditions": observed_postconditions,
        "after_schema_snapshot_sha256": after_schema_snapshot_sha256, "exit_code": 0,
        "ownership": copy.deepcopy(ownership),
    }
    journal["steps"].append(record)
    journal["status"] = IN_PROGRESS_REVIEW_ONLY
    return record


def stop_no_retry(
    journal: dict[str, Any], *, prepared_step_id: str, observed_postconditions: list[dict[str, Any]],
    after_schema_snapshot_sha256: str, exit_code: int, reason_code: str,
    ownership: dict[str, Any],
) -> dict[str, Any]:
    """Append terminal evidence for the unresolved PREPARED step; no retry path exists."""
    prepared, effective_owner = _outcome_prepared_and_owner(journal)
    _require_uuid(prepared_step_id, "Prepared step ID")
    if prepared["step_id"] != prepared_step_id or int(exit_code) == 0 or not reason_code:
        raise JournalViolation("Terminal outcome is invalid")
    _validate_observed(observed_postconditions, "Terminal observed postconditions")
    _require_sha256(after_schema_snapshot_sha256, "Terminal after snapshot")
    _validate_ownership(ownership, "Terminal outcome")
    if not _same_ownership(ownership, effective_owner):
        raise JournalViolation("Outcome ownership does not match the authorized PREPARED epoch")
    record = {
        "recorded_at_utc": utc_now(), "status": STOP_NO_RETRY, "step_id": prepared_step_id,
        "prepared_step_id": prepared_step_id, "statement_sha256": prepared["statement_sha256"],
        "observed_postconditions": observed_postconditions,
        "after_schema_snapshot_sha256": after_schema_snapshot_sha256,
        "exit_code": int(exit_code), "reason_code": reason_code, "retry_permitted": False,
        "ownership": copy.deepcopy(ownership),
    }
    journal["steps"].append(record)
    journal["terminal_record"] = record
    journal["status"] = STOP_NO_RETRY
    return record


def reconcile_prepared(
    journal: dict[str, Any], *, reconciliation_authorization: dict[str, Any],
    observed_reconciliation: list[dict[str, Any]], ownership: dict[str, Any],
) -> dict[str, Any]:
    """Append approval-bound reconciliation; it never executes or retries SQL."""
    _validate_journal_state(journal)
    if journal["status"] != PREPARED:
        raise JournalViolation("Only an unresolved PREPARED record can be reconciled")
    prepared, prior_ownership = _open_prepared(journal)
    _validate_ownership(ownership, "Reconciliation")
    if _same_ownership(ownership, prior_ownership):
        raise JournalViolation("Reconciliation requires a distinct ownership epoch")
    _validate_reconciliation_authorization(
        reconciliation_authorization,
        prepared_step_id=prepared["step_id"],
        prior_ownership=prior_ownership,
    )
    _validate_observed(observed_reconciliation, "Observed reconciliation", all_passed=True)
    record = {
        "recorded_at_utc": utc_now(), "status": RECONCILED,
        "step_id": prepared["step_id"], "prepared_step_id": prepared["step_id"],
        "statement_sha256": prepared["statement_sha256"],
        "prior_ownership": copy.deepcopy(prior_ownership), "ownership": copy.deepcopy(ownership),
        "reconciliation_authorization": copy.deepcopy(reconciliation_authorization),
        "observed_reconciliation": copy.deepcopy(observed_reconciliation),
    }
    journal["steps"].append(record)
    journal["status"] = RECONCILIATION_APPROVED
    return record


def _validate_step(
    record: Any, index: int, total: int, unresolved: dict[str, Any] | None,
    reconciliation: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(record, dict) or record.get("status") not in {PREPARED, RECONCILED, PASSED, STOP_NO_RETRY}:
        raise JournalViolation("Persisted journal step status is invalid")
    if not isinstance(record.get("recorded_at_utc"), str) or not record["recorded_at_utc"]:
        raise JournalViolation("Persisted step timestamp is invalid")
    _require_uuid(record.get("step_id"), "Persisted step ID")
    _require_sha256(record.get("statement_sha256"), "Persisted statement fingerprint")
    status = record["status"]
    if status == PREPARED:
        if unresolved is not None:
            raise JournalViolation("Only one PREPARED record may be unresolved")
        if not isinstance(record.get("preconditions"), list) or not isinstance(record.get("disposable_target_identity"), dict):
            raise JournalViolation("Prepared evidence is incomplete")
        if not isinstance(record.get("operator_approval_reference"), str) or not record["operator_approval_reference"]:
            raise JournalViolation("Prepared approval reference is invalid")
        _validate_observed(record.get("observed_preconditions"), "Persisted prepared preconditions", all_passed=True)
        _require_sha256(record.get("before_schema_snapshot_sha256"), "Persisted prepared before snapshot")
        _validate_ownership(record.get("ownership"), "Persisted prepared")
        return record, None
    if status == RECONCILED:
        if unresolved is None or reconciliation is not None:
            raise JournalViolation("Reconciliation has no unique unresolved PREPARED record")
        _validate_reconciliation_record(record, unresolved)
        return unresolved, record
    if unresolved is None or record.get("prepared_step_id") != unresolved.get("step_id") or record["step_id"] != unresolved.get("step_id"):
        raise JournalViolation("Outcome has no matching unresolved PREPARED record")
    if record["statement_sha256"] != unresolved["statement_sha256"]:
        raise JournalViolation("Outcome statement does not match PREPARED evidence")
    _validate_observed(record.get("observed_postconditions"), "Persisted outcome postconditions", all_passed=status == PASSED)
    _require_sha256(record.get("after_schema_snapshot_sha256"), "Persisted outcome after snapshot")
    _validate_ownership(record.get("ownership"), "Persisted outcome")
    expected_ownership = reconciliation["ownership"] if reconciliation is not None else unresolved["ownership"]
    if not _same_ownership(record["ownership"], expected_ownership):
        raise JournalViolation("Persisted outcome ownership does not match the authorized epoch")
    exit_code = record.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise JournalViolation("Persisted outcome exit code is invalid")
    if status == PASSED:
        if exit_code != 0:
            raise JournalViolation("PASSED outcome must have zero exit code")
    else:
        if index != total - 1 or exit_code == 0 or record.get("retry_permitted") is not False:
            raise JournalViolation("Terminal outcome contract is invalid")
        if not isinstance(record.get("reason_code"), str) or not record["reason_code"]:
            raise JournalViolation("Terminal outcome reason is invalid")
    return None, None


def _validate_journal_state(journal: dict[str, Any]) -> None:
    _validate_base(journal)
    status, steps, terminal = journal.get("status"), journal["steps"], journal.get("terminal_record")
    if status not in _LEGAL_TRANSITIONS:
        raise JournalViolation("Journal status is invalid")
    unresolved: dict[str, Any] | None = None
    reconciliation: dict[str, Any] | None = None
    for index, record in enumerate(steps):
        unresolved, reconciliation = _validate_step(record, index, len(steps), unresolved, reconciliation)
    if status == PENDING_REVIEW and (steps or terminal is not None):
        raise JournalViolation("Pending journal cannot contain progress")
    if status == PREPARED and (unresolved is None or reconciliation is not None or steps[-1]["status"] != PREPARED):
        raise JournalViolation("PREPARED journal requires one unresolved PREPARED record")
    if status == RECONCILIATION_APPROVED and (
        unresolved is None or reconciliation is None or steps[-1]["status"] != RECONCILED
    ):
        raise JournalViolation("Reconciliation-approved journal requires a verified reconciliation record")
    if status == IN_PROGRESS_REVIEW_ONLY and (not steps or unresolved is not None or reconciliation is not None or steps[-1]["status"] != PASSED or terminal is not None):
        raise JournalViolation("In-progress journal requires a completed successful prepared step")
    if status == STOP_NO_RETRY:
        if unresolved is not None or reconciliation is not None or not steps or not isinstance(terminal, dict) or terminal != steps[-1] or terminal.get("status") != STOP_NO_RETRY:
            raise JournalViolation("Terminal journal record is inconsistent")
    elif terminal is not None:
        raise JournalViolation("Non-terminal journal cannot contain terminal evidence")


def load_journal(path: Path) -> dict[str, Any]:
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise JournalViolation("Journal cannot be read as valid UTF-8 JSON") from None
    verify_integrity(journal)
    _validate_journal_state(journal)
    return journal


class JournalFileLock:
    """Nonblocking OS lock retained over read/verify/write/reload operations.

    A lock file marked ``held`` after a process crash is deliberately ambiguous:
    a future process fails closed rather than breaking it automatically.
    """

    def __init__(self, journal_path: Path, *, rehearsal_id: str, instance_id: str, run_nonce: str):
        if not rehearsal_id or not instance_id or not run_nonce:
            raise JournalViolation("Journal lock identity is required")
        self.journal_path = journal_path.resolve()
        self.lock_path = self.journal_path.with_name(f"{self.journal_path.name}.lock")
        self.metadata_path = self.journal_path.with_name(f"{self.journal_path.name}.lock.meta")
        self.rehearsal_id, self.instance_id, self.run_nonce = rehearsal_id, instance_id, run_nonce
        self._handle: Any | None = None

    def is_held_for(self, path: Path, rehearsal_id: str) -> bool:
        return self._handle is not None and path.resolve() == self.journal_path and rehearsal_id == self.rehearsal_id

    def _lock_os_handle(self, handle: Any) -> None:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_os_handle(self, handle: Any) -> None:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _open_fixed_lock_byte(self) -> Any:
        """Create/open one lock byte without append-mode metadata corruption."""
        if self.lock_path.is_symlink() or self.metadata_path.is_symlink():
            raise JournalViolation("Journal lock path substitution is refused")
        try:
            return self.lock_path.open("x+b")
        except FileExistsError:
            return self.lock_path.open("r+b")

    def _read_metadata(self) -> dict[str, Any] | None:
        if not self.metadata_path.exists():
            return None
        try:
            metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise JournalViolation("Journal lock metadata is invalid") from None
        if not isinstance(metadata, dict):
            raise JournalViolation("Journal lock metadata is invalid")
        return metadata

    def _write_metadata(self, state: str) -> None:
        metadata = {
            "state": state, "rehearsal_id": self.rehearsal_id,
            "instance_id": self.instance_id, "run_nonce": self.run_nonce,
            f"{state}_at_utc": utc_now(),
        }
        _atomic_write_bytes(self.metadata_path, _canonical_bytes(metadata) + b"\n")

    def acquire(self) -> "JournalFileLock":
        if self._handle is not None:
            raise JournalViolation("Journal lock is already held by this instance")
        handle: Any | None = None
        os_locked = False
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = self._open_fixed_lock_byte()
            self._lock_os_handle(handle)
            os_locked = True
            previous = self._read_metadata()
            if previous is not None and previous.get("state") != "released":
                raise JournalViolation("Ambiguous or stale journal lock requires independent review")
            self._write_metadata("held")
            self._handle = handle
            return self
        except JournalViolation:
            if handle is not None:
                try:
                    if os_locked:
                        self._unlock_os_handle(handle)
                    handle.close()
                except OSError:
                    pass
            raise
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            if handle is not None:
                try:
                    if os_locked:
                        self._unlock_os_handle(handle)
                    handle.close()
                except OSError:
                    pass
            raise JournalViolation("Journal lock acquisition failed; runner must stop") from None

    def release(self) -> None:
        if self._handle is None:
            return
        handle = self._handle
        try:
            self._write_metadata("released")
            self._unlock_os_handle(handle)
        except OSError:
            raise JournalViolation("Journal lock release failed; preserve evidence for review") from None
        finally:
            handle.close()
            self._handle = None


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except OSError:
        raise JournalViolation("Journal persistence failed; runner must stop") from None
    finally:
        try:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        except OSError:
            pass


def _assert_append_only(previous: dict[str, Any], candidate: dict[str, Any]) -> None:
    verify_integrity(previous)
    _validate_journal_state(previous)
    _validate_journal_state(candidate)
    old_meta = {key: value for key, value in previous.items() if key not in _MUTABLE_FIELDS}
    new_meta = {key: value for key, value in candidate.items() if key not in _MUTABLE_FIELDS}
    if old_meta != new_meta:
        raise JournalViolation("Persisted journal metadata is immutable")
    if candidate["status"] not in _LEGAL_TRANSITIONS[previous["status"]]:
        raise JournalViolation("Illegal journal status transition")
    if previous.get("terminal_record") is not None:
        if _canonical_bytes(previous) != _canonical_bytes(candidate):
            raise JournalViolation("Persisted terminal journal cannot be overwritten")
        return
    old_steps, new_steps = previous["steps"], candidate["steps"]
    if len(new_steps) < len(old_steps) or new_steps[:len(old_steps)] != old_steps:
        raise JournalViolation("Journal persistence is not append-only")


def _assert_one_durable_transition(previous: dict[str, Any] | None, candidate: dict[str, Any]) -> None:
    """Require a distinct durable PREPARED barrier before every outcome.

    Fresh state may persist exactly one PREPARED record. Thereafter each write
    may append exactly one matching outcome or the next PREPARED record, never
    a PREPARED/outcome batch. Byte-equivalent terminal persistence is allowed
    only as an idempotent reload-safe no-op.
    """
    if previous is None:
        if candidate["status"] != PREPARED or len(candidate["steps"]) != 1 or candidate["steps"][0]["status"] != PREPARED:
            raise JournalViolation("First durable write must contain exactly one PREPARED record")
        return
    if _canonical_bytes(previous) == _canonical_bytes(candidate):
        return
    old_steps, new_steps = previous["steps"], candidate["steps"]
    appended = new_steps[len(old_steps):]
    if len(appended) != 1:
        raise JournalViolation("Exactly one journal lifecycle transition is required per durable write")
    next_record = appended[0]
    old_status, new_status = previous["status"], candidate["status"]
    if old_status in {PENDING_REVIEW, IN_PROGRESS_REVIEW_ONLY}:
        if next_record["status"] != PREPARED or new_status != PREPARED:
            raise JournalViolation("Only one PREPARED transition may follow a completed state")
    elif old_status == PREPARED:
        if next_record["status"] == RECONCILED:
            if new_status != RECONCILIATION_APPROVED:
                raise JournalViolation("Reconciliation journal status is invalid")
            return
        if next_record["status"] not in {PASSED, STOP_NO_RETRY}:
            raise JournalViolation("PREPARED may transition only to reconciliation, PASSED, or STOP_NO_RETRY")
        expected = IN_PROGRESS_REVIEW_ONLY if next_record["status"] == PASSED else STOP_NO_RETRY
        if new_status != expected:
            raise JournalViolation("Prepared outcome journal status is invalid")
    elif old_status == RECONCILIATION_APPROVED:
        if next_record["status"] not in {PASSED, STOP_NO_RETRY}:
            raise JournalViolation("Reconciled PREPARED may transition only to PASSED or STOP_NO_RETRY")
        expected = IN_PROGRESS_REVIEW_ONLY if next_record["status"] == PASSED else STOP_NO_RETRY
        if new_status != expected:
            raise JournalViolation("Reconciled outcome journal status is invalid")
    else:
        raise JournalViolation("Terminal journal cannot append another lifecycle transition")


def write_journal(path: Path, journal: dict[str, Any], *, lock: Any) -> dict[str, Any]:
    """Persist under a held exclusive lock, then reload and verify the journal."""
    if path.is_symlink():
        raise JournalViolation("Journal path substitution is refused")
    if not getattr(lock, "is_held_for", lambda *_: False)(path, journal.get("rehearsal_id")):
        raise JournalViolation("A held matching journal lock is required for persistence")
    candidate = seal_journal(journal)
    _validate_journal_state(candidate)
    previous = load_journal(path) if path.exists() else None
    if previous is not None:
        _assert_append_only(previous, candidate)
    _assert_one_durable_transition(previous, candidate)
    _atomic_write_bytes(path, _canonical_bytes(candidate) + b"\n")
    persisted = load_journal(path)
    if _canonical_bytes(persisted) != _canonical_bytes(candidate):
        raise JournalViolation("Persisted journal differs from verified evidence; runner must stop")
    return persisted


class JournalMutation:
    """Exclusive mutation session for a future separately authorized runner.

    The caller must persist PREPARED successfully before any statement and must
    persist/verify an outcome before a later statement. This class never runs a
    statement itself.
    """

    def __init__(self, path: Path, initial: dict[str, Any], *, instance_id: str, run_nonce: str,
                 lock_factory: Any = JournalFileLock):
        _validate_journal_state(initial)
        self.path, self.initial = path, initial
        if not instance_id or not run_nonce:
            raise JournalViolation("Journal mutation ownership identity is required")
        self.instance_id, self.run_nonce = instance_id, run_nonce
        self.lock = lock_factory(path, rehearsal_id=initial["rehearsal_id"], instance_id=instance_id, run_nonce=run_nonce)
        self.journal: dict[str, Any] | None = None
        self._faulted = False
        self._ownership: dict[str, Any] | None = None
        self._reconciliation_required = False

    def _assert_healthy(self) -> None:
        if self._faulted:
            raise JournalViolation("Journal mutation session is fault-latched; independent review is required")

    def _fault(self) -> None:
        self._faulted = True

    def __enter__(self) -> "JournalMutation":
        self._assert_healthy()
        try:
            self.lock.acquire()
            self.journal = load_journal(self.path) if self.path.exists() else copy.deepcopy(self.initial)
            if self.journal["rehearsal_id"] != self.initial["rehearsal_id"] or self.journal["reviewed_sql_sha256"] != self.initial["reviewed_sql_sha256"]:
                raise JournalViolation("Journal identity does not match the requested mutation")
            if self.journal["status"] in {PREPARED, RECONCILIATION_APPROVED}:
                _, effective_owner = _open_prepared(self.journal)
                if (
                    effective_owner["instance_id"] == self.instance_id
                    and effective_owner["run_nonce"] == self.run_nonce
                ):
                    self._ownership = copy.deepcopy(effective_owner)
                else:
                    self._ownership = {
                        "epoch": _latest_ownership_epoch(self.journal) + 1,
                        "instance_id": self.instance_id,
                        "run_nonce": self.run_nonce,
                    }
                    self._reconciliation_required = True
            else:
                self._ownership = {
                    "epoch": _latest_ownership_epoch(self.journal) + 1,
                    "instance_id": self.instance_id,
                    "run_nonce": self.run_nonce,
                }
            return self
        except BaseException:
            self._fault()
            try:
                self.lock.release()
            except BaseException:
                pass
            raise

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.lock.release()

    def prepare_and_persist(self, **kwargs: Any) -> dict[str, Any]:
        if self._reconciliation_required:
            raise JournalViolation("Orphaned PREPARED requires reconciliation before another statement")
        if self._ownership is None:
            self._fault()
            raise JournalViolation("Journal mutation ownership is not initialized")
        kwargs["ownership"] = self._ownership
        return self._mutate_and_persist(prepare_step, **kwargs)

    def pass_and_persist(self, **kwargs: Any) -> dict[str, Any]:
        self._assert_outcome_authority(kwargs)
        return self._mutate_and_persist(record_pass, **kwargs)

    def stop_and_persist(self, **kwargs: Any) -> dict[str, Any]:
        self._assert_outcome_authority(kwargs)
        return self._mutate_and_persist(stop_no_retry, **kwargs)

    def reconcile_prepared_and_persist(
        self, *, reconciliation_authorization: dict[str, Any], observed_reconciliation: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist review approval for an orphaned PREPARED; never retries a statement."""
        self._assert_healthy()
        if not self._reconciliation_required or self._ownership is None:
            raise JournalViolation("This session has no orphaned PREPARED record to reconcile")
        persisted = self._mutate_and_persist(
            reconcile_prepared,
            reconciliation_authorization=reconciliation_authorization,
            observed_reconciliation=observed_reconciliation,
            ownership=self._ownership,
        )
        self._reconciliation_required = False
        return persisted

    def _assert_outcome_authority(self, kwargs: dict[str, Any]) -> None:
        self._assert_healthy()
        if self._reconciliation_required:
            raise JournalViolation("Orphaned PREPARED requires independently authorized reconciliation")
        if self._ownership is None:
            self._fault()
            raise JournalViolation("Journal mutation ownership is not initialized")
        kwargs["ownership"] = self._ownership

    def _mutate_and_persist(self, mutation: Any, **kwargs: Any) -> dict[str, Any]:
        self._assert_healthy()
        if self.journal is None:
            self._fault()
            raise JournalViolation("Journal mutation lock is not held")
        candidate = copy.deepcopy(self.journal)
        try:
            mutation(candidate, **kwargs)
            persisted = write_journal(self.path, candidate, lock=self.lock)
        except BaseException:
            self._fault()
            raise
        self.journal = persisted
        return persisted
