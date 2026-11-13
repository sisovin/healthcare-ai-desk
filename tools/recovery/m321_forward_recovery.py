"""M3.2.1 Phase A.2 — READ-ONLY recovery preflight (review candidate).

No DDL, DML, Alembic stamp, or recovery execution is implemented here.
Accepts only a NEW disposable MySQL instance on 127.0.0.1:34071 and an
independently collected Docker-inspect record plus operator attestation.
The historical 34068/34069/34070 instances are unconditionally rejected.

Credentials are supplied by the M321_A2_DATABASE_URL environment variable,
never as command-line arguments, diagnostic text or evidence JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

PINNED_HOST = "127.0.0.1"
PINNED_PORT = 34071
MYSQL_INTERNAL_PORT = 3306
DB_PATTERN = re.compile(r"had_m321_a2_[0-9a-f]{12}$")
EXPECTED_REVISION = "20261112_0011"
EXPECTED_COLLATION = "utf8mb4_unicode_ci"
EXPECTED_VERSION = re.compile(r"^8\.4\.[0-9]+(?:[.-].*)?$")
SCHEMA_VERSION = 1


class SafetyViolation(RuntimeError):
    """Fail-closed error. No recovery statement is ever executed."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_zero(count: int, label: str) -> None:
    if int(count) != 0:
        raise SafetyViolation(f"{label}: expected zero; received {count}")


def validate_target(raw_url: str) -> str:
    """Return validated database name; do not return or log a URL."""
    try:
        url = make_url(raw_url)
        if (url.drivername != "mysql+pymysql" or url.host != PINNED_HOST
            or url.port != PINNED_PORT or not DB_PATTERN.fullmatch(url.database or "")
            or not url.username or url.password is None or url.query):
            raise SafetyViolation("Only pinned NEW disposable mysql+pymysql target is accepted")
        return str(url.database)
    except SafetyViolation:
        raise
    except (ValueError, TypeError, AttributeError) as exc:
        raise SafetyViolation("Invalid database connection URL") from None


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SafetyViolation(f"Missing/invalid JSON evidence: {path.name}") from None


def validate_attestation(att: dict, inspect_json: Any, database: str, inspect_file: Path) -> str:
    """Validate independently acquired Docker evidence; not a cryptographic attestation."""
    if not isinstance(att, dict) or not isinstance(inspect_json, list) or len(inspect_json) != 1:
        raise SafetyViolation("Attestation/Docker-inspect document shape is invalid")
    item = inspect_json[0]
    if not isinstance(item, dict):
        raise SafetyViolation("Docker-inspect document is invalid")
    required = {"schema_version": SCHEMA_VERSION, "scope": "new_disposable_rehearsal",
                "database": database, "host": PINNED_HOST, "host_port": PINNED_PORT,
                "container_port": MYSQL_INTERNAL_PORT, "writers_stopped": True,
                "transactions_drained": True, "container_id": item.get("Id"),
                "docker_inspect_sha256": sha256_file(inspect_file)}
    for key, value in required.items():
        if not value or att.get(key) != value:
            raise SafetyViolation(f"Attestation mismatch or missing field: {key}")
    if not isinstance(att.get("server_uuid"), str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", att["server_uuid"]):
        raise SafetyViolation("Missing independently captured MySQL server UUID")
    if not att.get("operator") or not att.get("verified_by") or att["operator"] == att["verified_by"]:
        raise SafetyViolation("Operator and independent verifier must be identified and different")
    try:
        ts = datetime.fromisoformat(att["verified_at_utc"].replace("Z", "+00:00"))
        if ts.tzinfo is None or not (timedelta(0) <= datetime.now(timezone.utc) - ts.astimezone(timezone.utc) <= timedelta(hours=24)):
            raise ValueError("stale attestation")
    except (ValueError, TypeError, KeyError):
        raise SafetyViolation("Attestation must have recent UTC verification timestamp") from None
    if item.get("Name", "").lstrip("/").startswith("had-m321-a2-") is False:
        raise SafetyViolation("Unrecognized isolated Docker container name")
    if item.get("State", {}).get("Running") is not True:
        raise SafetyViolation("Docker container is not running")
    ports = item.get("HostConfig", {}).get("PortBindings", {}).get("3306/tcp", [])
    if len(ports) != 1 or ports[0].get("HostIp") != "127.0.0.1" or ports[0].get("HostPort") != "34071":
        raise SafetyViolation("Missing expected loopback-only Docker port binding")
    tmpfs = item.get("HostConfig", {}).get("Tmpfs", {})
    if not isinstance(tmpfs, dict) or "/var/lib/mysql" not in tmpfs:
        raise SafetyViolation("MySQL storage must be disposable tmpfs")
    mounts = item.get("Mounts", [])
    if any(m.get("Destination", "").startswith("/var/lib/mysql") for m in mounts):
        raise SafetyViolation("Refusing persistent host/volume MySQL data mount")
    image = item.get("Config", {}).get("Image", "")
    if not re.fullmatch(r"mysql:8\.4(?:\.[0-9]+)?", image):
        raise SafetyViolation("Unexpected MySQL Docker image tag")
    return item["Id"]


def assert_partial_schema(s: dict) -> None:
    """Pure, unit-testable structural fail-closed gate."""
    if s.get("revision") != EXPECTED_REVISION:
        raise SafetyViolation("Unexpected Alembic version")
    if s.get("protocol_table_count") != 0:
        raise SafetyViolation("Protocol table unexpectedly exists")
    if s.get("counter") != {"column_type": "int", "is_nullable": "YES", "column_default": None}:
        raise SafetyViolation("Not the documented nullable INT partial counter state")
    require_zero(s.get("counter_check_count", -1), "Pre-existing timeline counter CHECK")
    require_zero(s.get("exhausted_count", -1), "Signed-INT capacity")
    require_zero(s.get("other_sessions", -1), "Other open sessions")
    for table in ("conversations", "agent_profiles"):
        if s.get("uuid_columns", {}).get(table) != [
            ("id", "varchar", 36, "utf8mb4", EXPECTED_COLLATION),
            ("organization_id", "varchar", 36, "utf8mb4", EXPECTED_COLLATION),
        ]:
            raise SafetyViolation(f"Unexpected UUID column contract: {table}")
        if s.get("unique_indexes", {}).get(table) != [
            ("organization_id", 0), ("id", 0)
        ]:
            raise SafetyViolation(f"Composite unique key incorrect: {table}")


def inspect_read_only(url: str, db: str, att: dict) -> dict:
    """Uses read-only transactions; no schema-changing or data-changing statements."""
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("START TRANSACTION READ ONLY")
            def one(sql: str, **params: Any) -> Any:
                return conn.execute(text(sql), params).scalar_one()
            if one("SELECT DATABASE()") != db:
                raise SafetyViolation("Connected database identity mismatch")
            version = str(one("SELECT VERSION()"))
            port = int(one("SELECT @@port"))
            collation = one("SELECT @@collation_server")
            server_uuid = str(one("SELECT @@server_uuid"))
            if not EXPECTED_VERSION.fullmatch(version) or port != MYSQL_INTERNAL_PORT or collation != EXPECTED_COLLATION:
                raise SafetyViolation("MySQL 8.4 server contract mismatch")
            if server_uuid.lower() != att["server_uuid"].lower():
                raise SafetyViolation("Server UUID does not match independent attestation")
            actual_db_collation = one("SELECT DEFAULT_COLLATION_NAME FROM information_schema.schemata WHERE SCHEMA_NAME = :db", db=db)
            if actual_db_collation != EXPECTED_COLLATION:
                raise SafetyViolation("Database collation mismatch")
            grants = conn.exec_driver_sql("SHOW GRANTS FOR CURRENT_USER()").scalars().all()
            if not any(re.search(r"(?i)\b(PROCESS|ALL PRIVILEGES)\b.*\bON\s+\*\.\*", str(grant)) for grant in grants):
                raise SafetyViolation("PROCESS visibility is required to inspect all MySQL sessions")
            rev_rows = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            if len(rev_rows) != 1:
                raise SafetyViolation("Alembic version table must have exactly one row")
            s: dict = {"revision": rev_rows[0], "mysql_version": version, "server_uuid": server_uuid, "database": db}
            s["protocol_table_count"] = one("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='conversation_protocol_messages'")
            c = conn.execute(text("SELECT column_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='conversations' AND column_name='next_timeline_sequence'")).all()
            s["counter"] = dict(zip(("column_type", "is_nullable", "column_default"), c[0])) if len(c) == 1 else None
            s["counter_check_count"] = one("SELECT COUNT(*) FROM information_schema.check_constraints cc JOIN information_schema.table_constraints tc ON tc.constraint_schema=cc.constraint_schema AND tc.constraint_name=cc.constraint_name WHERE tc.table_schema=DATABASE() AND tc.table_name='conversations' AND cc.check_clause LIKE '%next_timeline_sequence%'")
            s["exhausted_count"] = one("SELECT COUNT(*) FROM (SELECT MAX(sequence_number) AS max_sequence FROM conversation_messages GROUP BY organization_id,conversation_id) AS seq WHERE max_sequence >= 2147483647")
            # Visibility of other connections may depend on PROCESS privilege: attestation is mandatory.
            s["other_sessions"] = one("SELECT COUNT(*) FROM information_schema.processlist WHERE db=DATABASE() AND id<>CONNECTION_ID()")
            s["other_transactions"] = one("SELECT COUNT(*) FROM information_schema.INNODB_TRX WHERE trx_mysql_thread_id <> CONNECTION_ID()")
            require_zero(s["other_transactions"], "Other InnoDB transactions")
            s["uuid_columns"] = {}
            s["unique_indexes"] = {}
            for table_name, index_name in (("conversations", "uq_conversations_org_id"), ("agent_profiles", "uq_agent_profiles_org_id")):
                rows = conn.execute(text("SELECT column_name,data_type,character_maximum_length,character_set_name,collation_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=:t AND column_name IN ('id','organization_id') ORDER BY column_name"), {"t": table_name}).all()
                s["uuid_columns"][table_name] = [tuple(r) for r in rows]
                idx = conn.execute(text("SELECT column_name,non_unique FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=:t AND index_name=:i ORDER BY seq_in_index"), {"t": table_name, "i": index_name}).all()
                s["unique_indexes"][table_name] = [tuple(r) for r in idx]
            assert_partial_schema(s)
            conn.rollback()
            return s
    finally:
        engine.dispose()


def build_review_evidence(*, db: str, inspection: dict, manifest_hashes: dict, att_hash: str, container_id: str) -> dict:
    return {
        "milestone": "M3.2.1 Phase A.2", "generated_at": utc_now(),
        "execution_authorization": False,
        "prohibited_actions": ["recovery_ddl", "alembic_reconciliation", "shared_environment_change", "writer_cutover", "m3_2_2_worker_activation"],
        "environment": {"database": db, "host": PINNED_HOST, "host_port": PINNED_PORT,
                        "container_id": container_id, "server_uuid": inspection["server_uuid"],
                        "mysql_version": inspection["mysql_version"], "isolation_check": "attested_and_read_only_verified"},
        "provenance": {"attestation_sha256": att_hash, "artifact_sha256": manifest_hashes,
                       "inspection_mode": "read_only", "commands_executed": ["START TRANSACTION READ ONLY", "SELECT ...", "ROLLBACK"]},
        "gates": {k: {"status": "pending", "evidence": []} for k in (
            "database_isolation", "populated_state_backfill", "negative_case_rejection",
            "schema_equivalence", "alembic_state_preserved", "partial_ddl_forward_recovery")},
        "read_only_preflight": {"status": "passed", "snapshot": inspection},
        "independent_review": {"reviewer": None, "reviewed_at_utc": None, "decision": "pending", "signature_or_reference": None},
        "decision": "awaiting_joint_review_no_execution_authorization"
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only M3.2.1 isolated NEW disposable recovery preflight")
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--docker-inspect-json", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--log-file", type=Path, required=True)
    args = parser.parse_args(argv)
    log: logging.Logger | None = None
    try:
        logging.Formatter.converter = __import__("time").gmtime
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        log = logging.getLogger("m321_readonly_preflight")
        log.setLevel(logging.INFO)
        log.propagate = False
        log.handlers.clear()
        handler = logging.FileHandler(args.log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)sZ %(levelname)s %(message)s"))
        log.addHandler(handler)
        url = __import__("os").environ.get("M321_A2_DATABASE_URL", "")
        db = validate_target(url)
        inspect_doc = load_json(args.docker_inspect_json)
        att = load_json(args.attestation)
        container_id = validate_attestation(att, inspect_doc, db, args.docker_inspect_json)
        log.info("Read-only preflight started: db=%s target_port=%s", db, PINNED_PORT)
        inspection = inspect_read_only(url, db, att)
        root = Path(__file__).resolve().parents[2]
        hashes = {p: sha256_file(root / p) for p in (
            "tools/recovery/m321_forward_recovery.py", "tools/recovery/m321_forward_recovery.sql",
            "tests/recovery/test_m321_forward_recovery.py")}
        report = build_review_evidence(db=db, inspection=inspection, manifest_hashes=hashes,
                                       att_hash=sha256_file(args.attestation), container_id=container_id)
        args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        log.info("Preflight PASS: evidence emitted; no DDL, DML or Alembic command executed")
        return 0
    except (SafetyViolation, SQLAlchemyError, OSError, ValueError, TypeError, KeyError) as exc:
        if log:
            log.error("STOP: safety or inspection error [%s]; no recovery executed", type(exc).__name__)
        print("M3.2.1 preflight failed closed; no recovery executed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
