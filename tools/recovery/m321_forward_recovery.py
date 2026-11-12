"""Fail-closed M3.2.1 forward-recovery operator tool.

Review artifact only. It intentionally has no recovery DDL implementation yet.
It may inspect a database only when explicitly invoked with a URL, and refuses
to target the shared/local Healthcare AI Desk database.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import re
import sys
from pathlib import Path
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


EXPECTED_REVISION = "20261112_0011"
EXPECTED_MYSQL_MAJOR = "8.4"
EXPECTED_MYSQL_CONTAINER_PORT = 3306
PINNED_HOST = "127.0.0.1"
PINNED_HOST_PORT = 34070
PINNED_DATABASE = "had_m32_recovery"
EXPECTED_COLLATION = "utf8mb4_unicode_ci"
REQUIRED_PARTIAL_COLUMN = "next_timeline_sequence"
FORBIDDEN_DATABASE_NAMES = {"healthcare_ai_desk", "mysql", "information_schema", "performance_schema", "sys"}


class RecoverySafetyError(RuntimeError):
    """Raised when the target is not the reviewed partial-DDL recovery state."""


@dataclass(frozen=True)
class RecoveryTarget:
    url: str
    expected_database: str
    expected_host: str
    expected_port: int
    log_file: str


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M3.2.1 forward-recovery safety gate (review artifact).")
    parser.add_argument("--database-url", required=True, help="Disposable MySQL SQLAlchemy URL only.")
    parser.add_argument("--expected-database", default=PINNED_DATABASE)
    parser.add_argument("--expected-host", default=PINNED_HOST)
    parser.add_argument("--expected-port", default=PINNED_HOST_PORT, type=int)
    parser.add_argument("--log-file", default="m321_forward_recovery.log")
    parser.add_argument("--writer-shutdown-attestation", required=True, help="Operator-created evidence file confirming writers/workers are disabled and transactions drained.")
    parser.add_argument("--inspect-only", action="store_true", help="Run preflight only; never modify state.")
    return parser


def _configure_logging(path: str) -> logging.Logger:
    logger = logging.getLogger("m321_forward_recovery")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s")
    for handler in (logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def _validate_url(target: RecoveryTarget) -> None:
    parsed = urlparse(target.url)
    if not parsed.scheme.startswith("mysql"):
        raise RecoverySafetyError("Only a MySQL URL is accepted.")
    if parsed.query or parsed.fragment or parsed.username is None or parsed.password is None:
        raise RecoverySafetyError("Connection URL must not contain extra parameters, fragments, or omit credentials.")
    if parsed.hostname != PINNED_HOST or parsed.port != PINNED_HOST_PORT:
        raise RecoverySafetyError("Recovery is pinned to 127.0.0.1:34070 only.")
        raise RecoverySafetyError("Connection URL host/port does not match the explicit operator target.")
    if parsed.path.lstrip("/") != PINNED_DATABASE:
        raise RecoverySafetyError("Connection URL database does not match the explicit operator target.")
    if target.expected_database != PINNED_DATABASE or target.expected_host != PINNED_HOST or target.expected_port != PINNED_HOST_PORT:
        raise RecoverySafetyError("Operator-supplied target must match the pinned disposable recovery target.")
    if target.expected_database in FORBIDDEN_DATABASE_NAMES:
        raise RecoverySafetyError("Refusing a shared/system database name.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", target.expected_database):
        raise RecoverySafetyError("Expected database name contains unsupported characters.")


def _validate_writer_shutdown_attestation(path: str) -> None:
    evidence = Path(path)
    if not evidence.is_file() or evidence.stat().st_size == 0:
        raise RecoverySafetyError("Independent writer-shutdown/transaction-drain attestation is required.")


def _scalar(connection, statement: str, **params):
    return connection.execute(text(statement), params).scalar_one()


def _preflight(engine: Engine, target: RecoveryTarget, logger: logging.Logger) -> None:
    with engine.connect() as connection:
        database = _scalar(connection, "SELECT DATABASE()")
        version = _scalar(connection, "SELECT VERSION()")
        mysql_port = _scalar(connection, "SELECT @@port")
        collation = _scalar(connection, "SELECT @@collation_server")
        if database != target.expected_database:
            raise RecoverySafetyError(f"Connected database {database!r} is not the expected disposable database.")
        if not str(version).startswith(EXPECTED_MYSQL_MAJOR + "."):
            raise RecoverySafetyError(f"MySQL version {version!r} is not the reviewed {EXPECTED_MYSQL_MAJOR}.x target.")
        if mysql_port != EXPECTED_MYSQL_CONTAINER_PORT or collation != EXPECTED_COLLATION:
            raise RecoverySafetyError("Disposable server port or collation does not match the reviewed recovery target.")

        revision = _scalar(connection, "SELECT version_num FROM alembic_version")
        if revision != EXPECTED_REVISION:
            raise RecoverySafetyError(f"Alembic revision {revision!r} is not expected partial-state revision {EXPECTED_REVISION!r}.")

        partial_column = _scalar(
            connection,
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'conversations' "
            "AND column_name = :column_name AND column_type = 'int' "
            "AND is_nullable = 'YES' AND column_default IS NULL",
            column_name=REQUIRED_PARTIAL_COLUMN,
        )
        if partial_column != 1:
            raise RecoverySafetyError("Expected nullable INT partial counter column is absent or differs.")

        protocol_table = _scalar(
            connection,
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = 'conversation_protocol_messages'",
        )
        if protocol_table != 0:
            raise RecoverySafetyError("Protocol table already exists; this is not the reviewed partial state.")

        counter_check = _scalar(
            connection,
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE table_schema = DATABASE() AND table_name = 'conversations' "
            "AND constraint_name = 'ck_conversations_next_timeline_sequence'",
        )
        if counter_check != 0:
            raise RecoverySafetyError("Counter CHECK already exists; this requires a different reviewed recovery path.")
        all_counter_checks = _scalar(connection, "SELECT COUNT(*) FROM information_schema.check_constraints cc JOIN information_schema.table_constraints tc ON tc.constraint_schema = cc.constraint_schema AND tc.constraint_name = cc.constraint_name WHERE tc.table_schema = DATABASE() AND tc.table_name = 'conversations' AND cc.check_clause LIKE '%next_timeline_sequence%'")
        if all_counter_checks != 0:
            raise RecoverySafetyError("Unexpected counter CHECK constraint already exists.")
        for table_name, index_name in (("conversations", "uq_conversations_org_id"), ("agent_profiles", "uq_agent_profiles_org_id")):
            columns = connection.execute(text("SELECT column_name, character_maximum_length, collation_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = :table_name AND column_name IN ('organization_id', 'id') ORDER BY column_name"), {"table_name": table_name}).all()
            index_columns = connection.execute(text("SELECT column_name FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = :table_name AND index_name = :index_name ORDER BY seq_in_index"), {"table_name": table_name, "index_name": index_name}).scalars().all()
            if len(columns) != 2 or any(length != 36 or item_collation != EXPECTED_COLLATION for _name, length, item_collation in columns) or index_columns != ["organization_id", "id"]:
                raise RecoverySafetyError(f"UUID/index compatibility failed for {table_name}.")

        active_writers = _scalar(
            connection,
            "SELECT COUNT(*) FROM information_schema.processlist "
            "WHERE db = DATABASE() AND command <> 'Sleep' AND id <> CONNECTION_ID()",
        )
        if active_writers != 0:
            raise RecoverySafetyError(f"Refusing recovery while {active_writers} active database session(s) exist.")

        logger.info("Preflight passed: database=%s mysql=%s mysql_port=%s collation=%s revision=%s partial_column=%s", database, version, mysql_port, collation, revision, REQUIRED_PARTIAL_COLUMN)


def _require_operator_confirmation(step: str) -> None:
    phrase = f"RECOVER {step}"
    answer = getpass.getpass(f"Type exactly '{phrase}' to authorize reviewed statement {step}: ")
    if answer != phrase:
        raise RecoverySafetyError(f"Operator did not authorize recovery step {step}.")


def main() -> int:
    args = _build_parser().parse_args()
    target = RecoveryTarget(args.database_url, args.expected_database, args.expected_host, args.expected_port, args.log_file)
    try:
        logger = _configure_logging(target.log_file)
        _validate_url(target)
        _validate_writer_shutdown_attestation(args.writer_shutdown_attestation)
        engine = create_engine(target.url, pool_pre_ping=True)
        _preflight(engine, target, logger)
        if args.inspect_only:
            logger.info("Inspect-only completed; no DDL or DML was executed.")
            return 0
        # Deliberately refuse execution until the exact SQL artifact is reviewed.
        _require_operator_confirmation("REVIEWED_SQL")
        raise RecoverySafetyError("Recovery DDL is intentionally unavailable until m321_forward_recovery.sql is jointly approved.")
    except (RecoverySafetyError, SQLAlchemyError, OSError) as exc:
        try:
            logger.error("Recovery stopped: %s", exc)
        except UnboundLocalError:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
