"""M3.2.1 review-only local evidence prototype: single writer + persisted PREPARED.

NO database connector, SQL executor, recovery approval, or integration with the
operational step journal. This is an independent offline implementation candidate.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReviewJournalError(RuntimeError):
    """Fail closed on ambiguous or unsafe evidence transitions."""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ReviewJournalError("Snapshot must be an existing ordinary local file")
    try:
        return _hash(path.read_bytes())
    except OSError:
        raise ReviewJournalError("Snapshot cannot be read") from None


def _require_observed(rows: list[dict[str, Any]], *, passing: bool) -> None:
    if not isinstance(rows, list) or not rows:
        raise ReviewJournalError("Observed evidence is required")
    for row in rows:
        if not isinstance(row, dict) or not all(k in row for k in ("check", "expected", "observed", "passed")):
            raise ReviewJournalError("Observed evidence fields missing")
        if not isinstance(row["passed"], bool) or not isinstance(row["check"], str) or not row["check"]:
            raise ReviewJournalError("Invalid observed assertion")
        if passing and row["passed"] is not True:
            raise ReviewJournalError("Failed assertion cannot be recorded as PASSED")


def _seal(document: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(document)
    item.pop("integrity", None)
    item["integrity"] = {"algorithm": "sha256", "content_sha256": _hash(_canonical(item))}
    return item


def _verify(document: dict[str, Any]) -> None:
    if not isinstance(document, dict) or document.get("review_only") is not True or document.get("execution_authorization") is not False:
        raise ReviewJournalError("Review-only and execution-hold flags are required")
    integrity = document.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        raise ReviewJournalError("Integrity seal missing")
    unsigned = copy.deepcopy(document)
    unsigned.pop("integrity", None)
    if integrity.get("content_sha256") != _hash(_canonical(unsigned)):
        raise ReviewJournalError("Journal integrity mismatch")
    events = document.get("events")
    if not isinstance(events, list):
        raise ReviewJournalError("Events must be a list")
    pending = None
    terminal = False
    sha_re = re.compile(r"^[0-9a-f]{64}$")
    for event in events:
        if not isinstance(event, dict) or not event.get("step_id") or not event.get("recorded_at_utc"):
            raise ReviewJournalError("Malformed journal event")
        kind = event.get("type")
        if terminal:
            raise ReviewJournalError("Events after terminal STOP_NO_RETRY")
        if kind == "PREPARED":
            if pending is not None or not sha_re.fullmatch(str(event.get("statement_sha256", ""))):
                raise ReviewJournalError("Invalid or concurrent PREPARED event")
            if not sha_re.fullmatch(str(event.get("before_snapshot_sha256", ""))) or _digest_file(Path(event.get("before_snapshot_path", ""))) != event["before_snapshot_sha256"]:
                raise ReviewJournalError("Before-snapshot evidence mismatched")
            _require_observed(event.get("observed_preconditions"), passing=True)
            pending = event["step_id"]
        elif kind == "PASSED":
            if pending != event["step_id"] or event.get("exit_code") != 0:
                raise ReviewJournalError("Unexpected PASSED event")
            _require_observed(event.get("observed_postconditions"), passing=True)
            if not sha_re.fullmatch(str(event.get("after_snapshot_sha256", ""))) or _digest_file(Path(event.get("after_snapshot_path", ""))) != event["after_snapshot_sha256"]:
                raise ReviewJournalError("After-snapshot evidence mismatched")
            pending = None
        elif kind == "STOP_NO_RETRY":
            if pending != event["step_id"] or not event.get("reason_code") or type(event.get("exit_code")) is not int or event["exit_code"] == 0:
                raise ReviewJournalError("Invalid terminal event")
            _require_observed(event.get("observed_postconditions"), passing=False)
            if not sha_re.fullmatch(str(event.get("after_snapshot_sha256", ""))) or _digest_file(Path(event.get("after_snapshot_path", ""))) != event["after_snapshot_sha256"]:
                raise ReviewJournalError("After-snapshot evidence mismatched")
            pending = None
            terminal = True
        else:
            raise ReviewJournalError("Unsupported journal event type")
    expected = "STOP_NO_RETRY" if terminal else "PREPARED" if pending else "READY_REVIEW_ONLY" if events else "PENDING_REVIEW"
    if document.get("status") != expected:
        raise ReviewJournalError("Journal status does not match event sequence")


class PreparedReviewStore:
    """Exclusive local-file session. Unresolved PREPARED refuses restart/resume.

    Callers may only generate evidence here; no statement is executed by this class.
    """

    def __init__(self, path: Path, *, rehearsal_id: str, reviewed_sql_sha256: str) -> None:
        self.path = Path(path)
        self.lock_path = Path(str(self.path) + ".lock")
        self.rehearsal_id = rehearsal_id
        self.sql_sha256 = reviewed_sql_sha256
        self._lock_fd: int | None = None
        self._document: dict[str, Any] | None = None
        self._current_hash: str | None = None
        self._blocked = False
        if not self.rehearsal_id or len(self.sql_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sql_sha256):
            raise ReviewJournalError("Rehearsal identity and reviewed SQL SHA-256 required")

    def __enter__(self) -> "PreparedReviewStore":
        if self.path.is_symlink() or self.lock_path.is_symlink():
            raise ReviewJournalError("Symlink journal paths are forbidden")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError:
            raise ReviewJournalError("Exclusive journal writer lock unavailable; stop, do not break lock") from None
        self._lock_fd = fd
        try:
            payload = _canonical({"pid": os.getpid(), "rehearsal_id": self.rehearsal_id, "nonce": uuid.uuid4().hex, "created_at_utc": _utc()})
            os.write(fd, payload)
            os.fsync(fd)
            if self.path.exists():
                data = self.path.read_bytes()
                obj = json.loads(data.decode("utf-8"))
                _verify(obj)
                if obj.get("rehearsal_id") != self.rehearsal_id or obj.get("reviewed_sql_sha256") != self.sql_sha256:
                    raise ReviewJournalError("Journal identity mismatch")
                if obj["status"] in {"PREPARED", "STOP_NO_RETRY"}:
                    raise ReviewJournalError("Unresolved or terminal journal; no resume and no retry")
                self._document, self._current_hash = obj, _hash(data)
            else:
                self._document = {
                    "schema_version": 1, "milestone": "M3.2.1 Phase A.2", "rehearsal_id": self.rehearsal_id,
                    "reviewed_sql_sha256": self.sql_sha256, "created_at_utc": _utc(),
                    "execution_authorization": False, "review_only": True, "status": "PENDING_REVIEW", "events": [],
                }
                self._persist(self._document)
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_args: object) -> None:
        if self._lock_fd is not None:
            fd, self._lock_fd = self._lock_fd, None
            try:
                os.close(fd)
                self.lock_path.unlink()  # Only lock held by this instance; errors fail closed on next open.
            except OSError:
                self._blocked = True

    def _persist(self, candidate: dict[str, Any]) -> None:
        if self._blocked or self._lock_fd is None:
            raise ReviewJournalError("Journal writer is not exclusively locked")
        try:
            if self._current_hash is not None:
                if not self.path.is_file() or _hash(self.path.read_bytes()) != self._current_hash:
                    raise ReviewJournalError("Journal changed outside exclusive writer session")
            sealed = _seal(candidate)
            _verify(sealed)
            if self._document is not None and self._current_hash is not None:
                previous = self._document
                old = previous["events"]
                if {k:v for k,v in previous.items() if k not in {"events", "status", "integrity"}} != {k:v for k,v in sealed.items() if k not in {"events", "status", "integrity"}}:
                    raise ReviewJournalError("Immutable metadata modification")
                if sealed["events"][:len(old)] != old or len(sealed["events"]) < len(old):
                    raise ReviewJournalError("Step history mutation")
            descriptor, temp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".m321-prepared-", suffix=".tmp")
            try:
                with os.fdopen(descriptor, "wb") as fp:
                    fp.write(_canonical(sealed) + b"\n")
                    fp.flush()
                    os.fsync(fp.fileno())
                os.replace(temp_name, self.path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            stored_bytes = self.path.read_bytes()
            restored = json.loads(stored_bytes.decode("utf-8"))
            _verify(restored)
            if restored != sealed:
                raise ReviewJournalError("Durable reload differs from candidate")
            self._current_hash = _hash(stored_bytes)
            self._document = sealed
        except Exception as exc:
            self._blocked = True
            if isinstance(exc, ReviewJournalError):
                raise
            raise ReviewJournalError("Journal write/reload failed; stop without retry") from None

    def prepare(self, *, step_id: str, statement: str, observed_preconditions: list[dict[str, Any]], before_snapshot: Path) -> None:
        if self._document is None or self._document["status"] not in {"PENDING_REVIEW", "READY_REVIEW_ONLY"}:
            raise ReviewJournalError("Cannot prepare with unresolved or terminal state")
        if not step_id or not statement.strip() or any(e["step_id"] == step_id for e in self._document["events"]):
            raise ReviewJournalError("Step identity is invalid or repeated")
        _require_observed(observed_preconditions, passing=True)
        next_doc = copy.deepcopy(self._document)
        next_doc["events"].append({
            "type": "PREPARED", "step_id": step_id, "recorded_at_utc": _utc(),
            "statement_sha256": _hash(statement.encode("utf-8")),
            "observed_preconditions": observed_preconditions,
            "before_snapshot_path": str(before_snapshot), "before_snapshot_sha256": _digest_file(Path(before_snapshot)),
        })
        next_doc["status"] = "PREPARED"
        self._persist(next_doc)

    def record_pass(self, *, step_id: str, observed_postconditions: list[dict[str, Any]], after_snapshot: Path) -> None:
        if self._document is None or self._document["status"] != "PREPARED" or self._document["events"][-1]["step_id"] != step_id:
            raise ReviewJournalError("No matching persisted PREPARED step")
        _require_observed(observed_postconditions, passing=True)
        next_doc = copy.deepcopy(self._document)
        next_doc["events"].append({
            "type": "PASSED", "step_id": step_id, "recorded_at_utc": _utc(), "exit_code": 0,
            "observed_postconditions": observed_postconditions,
            "after_snapshot_path": str(after_snapshot), "after_snapshot_sha256": _digest_file(Path(after_snapshot)),
        })
        next_doc["status"] = "READY_REVIEW_ONLY"
        self._persist(next_doc)

    def stop_no_retry(self, *, step_id: str, reason_code: str, exit_code: int, observed_postconditions: list[dict[str, Any]], after_snapshot: Path) -> None:
        if self._document is None or self._document["status"] != "PREPARED" or self._document["events"][-1]["step_id"] != step_id:
            raise ReviewJournalError("No matching persisted PREPARED step")
        if not reason_code or type(exit_code) is not int or exit_code == 0:
            raise ReviewJournalError("Terminal failure requires nonzero exit and reason")
        _require_observed(observed_postconditions, passing=False)
        next_doc = copy.deepcopy(self._document)
        next_doc["events"].append({
            "type": "STOP_NO_RETRY", "step_id": step_id, "recorded_at_utc": _utc(),
            "exit_code": exit_code, "reason_code": reason_code, "retry_permitted": False,
            "observed_postconditions": observed_postconditions,
            "after_snapshot_path": str(after_snapshot), "after_snapshot_sha256": _digest_file(Path(after_snapshot)),
        })
        next_doc["status"] = "STOP_NO_RETRY"
        self._persist(next_doc)

    @property
    def snapshot(self) -> dict[str, Any]:
        if self._document is None:
            raise ReviewJournalError("Journal not loaded")
        return copy.deepcopy(self._document)
