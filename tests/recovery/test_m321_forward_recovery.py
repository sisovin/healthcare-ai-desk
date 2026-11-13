"""M3.2.1 Phase A.2: offline negative checks + OPTIONAL NEW-disposable rehearsal.

Default pytest execution is completely offline and never opens a database.
The live integration test is skipped unless ALL independent approvals and
artifact/snapshot inputs exist. Current approval status is FALSE: DO NOT RUN.
Only a brand-new, already-provisioned MySQL 8.4 schema at revision 0011 with
an injected nullable counter partial-state is in scope. Preserved DBs forbidden.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, create_engine, inspect as sa_inspect, text
from sqlalchemy.sql.sqltypes import Boolean, Date, DateTime, Integer, LargeBinary, Numeric, String, Text

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PACKAGE_ROOT / "tools/recovery/m321_forward_recovery.py"
SQL_FILE = PACKAGE_ROOT / "tools/recovery/m321_forward_recovery.sql"
_spec = importlib.util.spec_from_file_location("m321_forward_recovery", SCRIPT)
assert _spec is not None and _spec.loader is not None
import sys
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
r = _module

STEPS = (
    "overflow_preflight", "backfill", "backfill_postcondition",
    "add_counter_check", "enforce_counter_not_null", "create_protocol_table",
    "create_conversation_time_index", "create_recipient_time_index",
)
EXPECTED_CHECKS = {
    "ck_conversation_protocol_messages_sender_type",
    "ck_conversation_protocol_messages_recipient_type",
    "ck_conversation_protocol_messages_recipient_identity",
    "ck_conversation_protocol_messages_type",
    "ck_conversation_protocol_messages_classification",
}
EXPECTED_UNIQUES = {
    "uq_conversation_protocol_messages_org_id": ["organization_id", "id"],
    "uq_conversation_protocol_messages_org_conversation_sequence": ["organization_id", "conversation_id", "sequence_number"],
    "uq_conversation_protocol_messages_org_conversation_idempotency": ["organization_id", "conversation_id", "idempotency_key"],
}
EXPECTED_SECONDARY = {
    "ix_conversation_protocol_messages_org_conversation_time": ["organization_id", "conversation_id", "created_at"],
    "ix_conversation_protocol_messages_org_recipient_time": ["organization_id", "recipient_type", "recipient_agent_profile_id", "created_at"],
}
EXPECTED_FK = {
    (("organization_id", "conversation_id"), "conversations", ("organization_id", "id"), "CASCADE"),
    (("organization_id", "sender_agent_profile_id"), "agent_profiles", ("organization_id", "id"), "RESTRICT"),
    (("organization_id", "recipient_agent_profile_id"), "agent_profiles", ("organization_id", "id"), "RESTRICT"),
}


def parse_review_sql(path: Path = SQL_FILE) -> list[tuple[str, str]]:
    """Exact marked statements; never pass arbitrary full SQL to connection."""
    source = path.read_text(encoding="utf-8")
    chunks = re.split(r"(?m)^-- @step ([a-z_]+)[^\n]*\n", source)
    if any(line.strip() and not line.lstrip().startswith("--") for line in chunks[0].splitlines()):
        raise r.SafetyViolation("Unmarked SQL content found before first statement")
    if len(chunks) != 1 + 2 * len(STEPS):
        raise r.SafetyViolation("Incorrect number of reviewed statements")
    statements = []
    for i in range(1, len(chunks), 2):
        name, body = chunks[i], chunks[i + 1]
        statement, separator, after = body.partition(";")
        if not separator or any(line.strip() and not line.lstrip().startswith("--") for line in after.splitlines()):
            raise r.SafetyViolation(f"Unexpected additional SQL content: {name}")
        statements.append((name, statement.strip()))
        if not statements[-1][1]:
            raise r.SafetyViolation(f"Empty SQL statement: {name}")
    if tuple(n for n, _ in statements) != STEPS:
        raise r.SafetyViolation("Unexpected reviewed statement order")
    for name, statement in statements:
        if (";" in statement or re.search(r"\balembic_version\b", statement, re.I)
            or re.match(r"(?i)^(DROP|TRUNCATE|DELETE|REPLACE|GRANT|REVOKE|ALTER\s+USER)\b", statement)):

            raise r.SafetyViolation(f"Unapproved operation in statement: {name}")
    return statements


def test_sql_contract_names_match_authoritative_0012_ast():
    """Offline source-to-SQL name coverage only; not physical DDL equivalence."""
    import ast
    authoritative = PACKAGE_ROOT / "evidence/20261112_0012_protocol_message_contract.py"
    tree = ast.parse(authoritative.read_text(encoding="utf-8"))
    checks, uniques, indexes, foreign_keys = set(), set(), set(), 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        which = node.func.attr
        kwargs = {k.arg: k.value for k in node.keywords if k.arg}
        if which == "CheckConstraint" and isinstance(kwargs.get("name"), ast.Constant):
            checks.add(kwargs["name"].value)
        if which == "UniqueConstraint" and isinstance(kwargs.get("name"), ast.Constant):
            uniques.add(kwargs["name"].value)
        if which == "ForeignKeyConstraint":
            foreign_keys += 1
        if which == "create_index" and node.args and isinstance(node.args[0], ast.Constant):
            indexes.add(node.args[0].value)
    assert checks == EXPECTED_CHECKS
    assert uniques == set(EXPECTED_UNIQUES)
    assert indexes == set(EXPECTED_SECONDARY)
    assert foreign_keys == 3
    sql = SQL_FILE.read_text(encoding="utf-8")
    for name in checks | uniques | indexes | {"ck_conversations_next_timeline_sequence"}:
        assert len(re.findall(r"\b" + re.escape(name) + r"\b", sql)) >= 1
    assert sql.count("FOREIGN KEY (") == 3


def test_reviewed_step_order_is_frozen():
    steps = parse_review_sql()
    assert tuple(name for name, _ in steps) == STEPS
    assert steps[0][1].upper().startswith("SELECT ")
    assert steps[1][1].upper().startswith("UPDATE ")
    assert steps[2][1].upper().startswith("SELECT ")
    assert sum(sql.upper().startswith("ALTER TABLE") for _, sql in steps) == 2
    assert sum(sql.upper().startswith("CREATE") for _, sql in steps) == 3


@pytest.mark.parametrize("bad_url", [
    "mysql+pymysql://u:p@127.0.0.1:34070/had_m32_recovery",
    "mysql+pymysql://u:p@127.0.0.1:34069/had_m32_rehearsal_unicode",
    "mysql+pymysql://u:p@127.0.0.1:3306/healthcare_ai_desk",
    "mysql+pymysql://u:p@192.168.1.2:34071/had_m321_a2_123456789abc",
    "mysql+pymysql://u:p@127.0.0.1:34071/mysql",
    "mysql+pymysql://u:p@127.0.0.1:34071/had_m321_a2_123456789abc?unix_socket=/tmp/mysql.sock",
    "mysql+mysqldb://u:p@127.0.0.1:34071/had_m321_a2_123456789abc",
])
def test_bad_target_refused(bad_url):
    with pytest.raises(r.SafetyViolation):
        r.validate_target(bad_url)


def test_approved_shape_url_is_not_authorization():
    assert r.validate_target("mysql+pymysql://u:p@127.0.0.1:34071/had_m321_a2_123456789abc") == "had_m321_a2_123456789abc"


def _partial() -> dict:
    return {"revision": "20261112_0011", "protocol_table_count": 0,
            "counter": {"column_type": "int", "is_nullable": "YES", "column_default": None},
            "counter_check_count": 0, "exhausted_count": 0, "other_sessions": 0,
            "uuid_columns": {t: [("id", "varchar", 36, "utf8mb4", "utf8mb4_unicode_ci"),
                                  ("organization_id", "varchar", 36, "utf8mb4", "utf8mb4_unicode_ci")]
                             for t in ("conversations", "agent_profiles")},
            "unique_indexes": {t: [("organization_id", 0), ("id", 0)]
                               for t in ("conversations", "agent_profiles")}}


@pytest.mark.parametrize("field,value", [
    ("revision", "20261112_0012"), ("protocol_table_count", 1),
    ("counter_check_count", 1), ("exhausted_count", 1), ("other_sessions", 1),
    ("counter", {"column_type": "int", "is_nullable": "NO", "column_default": "1"}),
])
def test_unexpected_partial_schema_is_rejected(field, value):
    s = _partial()
    s[field] = value
    with pytest.raises(r.SafetyViolation):
        r.assert_partial_schema(s)


def test_expected_partial_schema_only_satisfies_shape_gate():
    r.assert_partial_schema(_partial())


def test_failed_postcondition_stops():
    with pytest.raises(r.SafetyViolation):
        r.require_zero(1, "invalid_backfill_count")


class _MemoryPath:
    """Minimal in-memory Path double: keeps default tests filesystem-free."""
    def __init__(self, name: str, content: str = ""):
        self.name = name
        self.content = content
        self.parent = self

    def read_bytes(self):
        return self.content.encode("utf-8")

    def read_text(self, *, encoding: str):
        return self.content

    def write_text(self, content: str, *, encoding: str):
        self.content = content
        return len(content)

    def mkdir(self, *, parents: bool, exist_ok: bool):
        return None


class _MissingPath:
    name = "not-there.json"

    def read_text(self, *, encoding: str):
        raise FileNotFoundError(self.name)


def test_missing_or_invalid_attestation_refused():
    wrong = _MemoryPath("attestation.json", "{}")
    with pytest.raises(r.SafetyViolation):
        r.validate_attestation({}, [], "had_m321_a2_123456789abc", wrong)
    with pytest.raises(r.SafetyViolation):
        r.load_json(_MissingPath())


def test_review_evidence_never_grants_execution():
    ev = r.build_review_evidence(db="had_m321_a2_123456789abc",
        inspection={"mysql_version": "8.4.13", "server_uuid": str(uuid4())},
        manifest_hashes={}, att_hash="0" * 64, container_id="a" * 64)
    assert ev["execution_authorization"] is False
    assert ev["independent_review"]["decision"] == "pending"
    assert all(v["status"] == "pending" for v in ev["gates"].values())


def _synthetic_attestation():
    """Pure offline fake Docker evidence for validation-unit-tests only."""
    container_id = "a" * 64
    inspect_doc = [{
        "Id": container_id, "Name": "/had-m321-a2-fixture", "State": {"Running": True},
        "HostConfig": {"PortBindings": {"3306/tcp": [{"HostIp": "127.0.0.1", "HostPort": "34071"}]},
                       "Tmpfs": {"/var/lib/mysql": "rw,noexec,nosuid"}},
        "Mounts": [], "Config": {"Image": "mysql:8.4"},
    }]
    doc_file = _MemoryPath("docker_inspect_synthetic.json", json.dumps(inspect_doc))
    database = "had_m321_a2_123456789abc"
    att = {
        "schema_version": 1, "scope": "new_disposable_rehearsal", "database": database,
        "host": "127.0.0.1", "host_port": 34071, "container_port": 3306,
        "writers_stopped": True, "transactions_drained": True,
        "container_id": container_id, "docker_inspect_sha256": r.sha256_file(doc_file),
        "server_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "operator": "synthetic-operator", "verified_by": "synthetic-reviewer",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return att, inspect_doc, database, doc_file


def test_valid_structured_attestation_shape_offline():
    att, doc, db, path = _synthetic_attestation()
    assert r.validate_attestation(att, doc, db, path) == "a" * 64


@pytest.mark.parametrize("bad_field,bad_value", [
    ("host_port", 34070), ("database", "had_m32_recovery"),
    ("writers_stopped", False), ("transactions_drained", False),
    ("verified_by", "synthetic-operator"),
    ("verified_at_utc", "2025-01-01T00:00:00+00:00"),
    ("docker_inspect_sha256", "0" * 64),
])
def test_invalid_structured_attestation_refused(bad_field, bad_value):
    att, doc, db, path = _synthetic_attestation()
    att[bad_field] = bad_value
    with pytest.raises(r.SafetyViolation):
        r.validate_attestation(att, doc, db, path)


def test_non_disposable_volume_refused():
    att, doc, db, path = _synthetic_attestation()
    doc[0]["Mounts"].append({"Destination": "/var/lib/mysql", "Type": "volume"})
    path.write_text(json.dumps(doc), encoding="utf-8")
    att["docker_inspect_sha256"] = r.sha256_file(path)
    with pytest.raises(r.SafetyViolation):
        r.validate_attestation(att, doc, db, path)


def test_non_loopback_port_binding_refused():
    att, doc, db, path = _synthetic_attestation()
    doc[0]["HostConfig"]["PortBindings"]["3306/tcp"][0]["HostIp"] = "0.0.0.0"
    path.write_text(json.dumps(doc), encoding="utf-8")
    att["docker_inspect_sha256"] = r.sha256_file(path)
    with pytest.raises(r.SafetyViolation):
        r.validate_attestation(att, doc, db, path)


# ---- Below this point: a separately approved, disposable-only INTEGRATION test.
# Existing/preserved/shared environments are ALWAYS rejected.
# The approval MUST be independently reviewed; operator cannot self-approve.
# Do not set these flags or run this test during the current execution hold.

INTEGRATION_ENABLED = os.environ.get("M321_A2_APPROVED_DISPOSABLE_REHEARSAL", "") == "1"


def _rehearsal_inputs():
    if not INTEGRATION_ENABLED:
        pytest.skip("Execution HOLD: no independently approved disposable rehearsal")
    approval_file = Path(os.environ.get("M321_A2_APPROVAL_JSON", ""))
    att_file = Path(os.environ.get("M321_A2_ATTESTATION_JSON", ""))
    docker_file = Path(os.environ.get("M321_A2_DOCKER_INSPECT_JSON", ""))
    reference_file = Path(os.environ.get("M321_A2_UNICODE_REFERENCE_JSON", ""))
    # No fallback/simulation: missing reference and approval fail before connection.
    for f in (approval_file, att_file, docker_file, reference_file):
        if not f.is_file():
            raise r.SafetyViolation("Missing independently required rehearsal artifact")
    url = os.environ.get("M321_A2_DATABASE_URL", "")
    db = r.validate_target(url)
    att, insp, approval = (r.load_json(f) for f in (att_file, docker_file, approval_file))
    container_id = r.validate_attestation(att, insp, db, docker_file)
    now = datetime.now(timezone.utc)
    if (approval.get("scope") != "disposable_rehearsal_only"
        or approval.get("recovery_ddl_approved") is not True
        or approval.get("shared_environment_approved") is not False
        or approval.get("database") != db or approval.get("container_id") != container_id
        or approval.get("sql_sha256") != r.sha256_file(SQL_FILE)
        or not approval.get("reviewer") or approval["reviewer"] == att["operator"]):
        raise r.SafetyViolation("Independent disposable-only authorization not present or mismatched")
    try:
        expiry = datetime.fromisoformat(approval["expires_at_utc"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or not now < expiry.astimezone(timezone.utc) <= now + timedelta(hours=24):
            raise ValueError("approval stale")
    except (KeyError, TypeError, ValueError):
        raise r.SafetyViolation("Invalid review approval expiry") from None
    reference = r.load_json(reference_file)
    if not isinstance(reference, dict) or reference.get("provenance", {}).get("source_environment") != "successful_0012_unicode_rehearsal" or not reference.get("schema"):
        raise r.SafetyViolation("Missing archived successful 0012 reference schema")
    return url, db, att, approval, reference


def _fresh_seed(conn):
    """Seed synthetic organization/user/project and conversations 0,1,7.

    Requires actual 0011 schema already present and no preexisting conversations
    or messages. Explicitly refuses to reuse already-populated environments.
    """
    if int(conn.execute(text("SELECT COUNT(*) FROM conversations")).scalar_one()) != 0:
        raise r.SafetyViolation("Fresh rehearsal requires zero existing conversations")
    if int(conn.execute(text("SELECT COUNT(*) FROM conversation_messages")).scalar_one()) != 0:
        raise r.SafetyViolation("Fresh rehearsal requires zero existing messages")
    # Existing 0011 schema must contain these expected core columns.
    org, owner, project = (str(uuid4()) for _ in range(3))
    conn.execute(text("INSERT INTO organizations (id,name,slug) VALUES (:id,'M321 Synthetic Org',:slug)"),
                 {"id": org, "slug": "m321-synthetic-" + org[:8]})
    conn.execute(text("INSERT INTO users (id,email,display_name,password_hash) VALUES (:id,:email,'Synthetic Test User','not-a-real-password-hash')"),
                 {"id": owner, "email": "synthetic-" + owner[:8] + "@example.invalid"})
    conn.execute(text("INSERT INTO projects (id,organization_id,name,slug) VALUES (:id,:org,'M321 Test Project',:slug)"),
                 {"id": project, "org": org, "slug": "m321-project-" + project[:8]})
    conn.execute(text("INSERT INTO organization_memberships (id,organization_id,user_id,role) VALUES (:id,:org,:usr,'owner')"),
                 {"id": str(uuid4()), "org": org, "usr": owner})
    ids = [str(uuid4()) for _ in range(3)]
    for cid in ids:
        conn.execute(text("INSERT INTO conversations (id,organization_id,project_id,created_by_user_id,title,status) VALUES (:id,:org,:project,:user,'M321 synthetic rehearsal','active')"),
                     {"id": cid, "org": org, "project": project, "user": owner})
    messages = Table("conversation_messages", MetaData(), autoload_with=conn)
    for index, max_seq in enumerate((0, 1, 7)):
        for seq in range(1, max_seq + 1):
            fields = {"id": str(uuid4()), "organization_id": org,
                      "conversation_id": ids[index], "sequence_number": seq}
            # Populate recognized OPTIONAL fields as well: sender-identity CHECK
            # constraints may require sender_user_id although it is nullable.
            known_fields = {
                "sender_type": "user", "sender_user_id": owner,
                "content_ciphertext": "synthetic-ciphertext-only",
                "content_redacted": "[synthetic text]",
                "data_classification": "internal",
                "idempotency_key": f"m321-{index}-{seq}",
                "request_fingerprint": hashlib.sha256(f"m321-{index}-{seq}".encode()).hexdigest(),
                "message_type": "user_message", "role": "user",
            }
            for name, value in known_fields.items():
                if name in messages.columns:
                    fields[name] = value
            for col in messages.columns:
                if col.name in fields or col.default is not None or col.server_default is not None or col.nullable:
                    continue
                name = col.name
                special = {
                    "sender_type": "user", "sender_user_id": owner, "sender_agent_profile_id": None,
                    "content_ciphertext": "synthetic-ciphertext-only", "content_redacted": "[synthetic text]",
                    "data_classification": "internal", "idempotency_key": f"m321-{index}-{seq}",
                    "request_fingerprint": hashlib.sha256(f"m321-{index}-{seq}".encode()).hexdigest(),
                    "message_type": "user_message", "status": "sent", "role": "user",
                }
                if name in special:
                    fields[name] = special[name]
                elif isinstance(col.type, (String, Text)):
                    raise r.SafetyViolation(f"Unrecognized required message string column: {name}")
                elif isinstance(col.type, (Integer, Numeric)):
                    raise r.SafetyViolation(f"Unrecognized required message numeric column: {name}")
                elif isinstance(col.type, Boolean):
                    fields[name] = False
                elif isinstance(col.type, DateTime):
                    fields[name] = datetime.now(timezone.utc).replace(tzinfo=None)
                elif isinstance(col.type, Date):
                    fields[name] = date.today()
                elif isinstance(col.type, LargeBinary):
                    raise r.SafetyViolation(f"Unrecognized required binary column: {name}")
                else:
                    raise r.SafetyViolation(f"Unrecognized required message column: {name}")
            conn.execute(messages.insert().values(**fields))
    return org, ids


def _assert_counters(conn, org, ids):
    found = conn.execute(text("SELECT id,next_timeline_sequence FROM conversations WHERE organization_id=:org"),
                         {"org": org}).all()
    mapping = {row[0]: int(row[1]) for row in found}
    if mapping != dict(zip(ids, (1, 2, 8))):
        raise r.SafetyViolation(f"Backfill counters incorrect; expected [1,2,8], got {sorted(mapping.values())}")


def _capture_schema(conn):
    """Normalized semantic snapshot: excludes MySQL auto-generated FK names."""
    def query(sql):
        return [list(row) for row in conn.execute(text(sql)).all()]
    cols = query("SELECT column_name,column_type,is_nullable,column_default,character_set_name,collation_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='conversation_protocol_messages' ORDER BY ordinal_position")
    indices = query("SELECT index_name,seq_in_index,column_name,non_unique FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='conversation_protocol_messages' ORDER BY index_name,seq_in_index")
    checks = query("SELECT cc.constraint_name,cc.check_clause,tc.enforced FROM information_schema.check_constraints cc JOIN information_schema.table_constraints tc ON tc.constraint_schema=cc.constraint_schema AND tc.constraint_name=cc.constraint_name WHERE tc.table_schema=DATABASE() AND tc.table_name='conversation_protocol_messages' ORDER BY cc.constraint_name")
    fks = query("SELECT k.constraint_name,k.column_name,k.referenced_table_name,k.referenced_column_name,k.ordinal_position,rc.delete_rule FROM information_schema.key_column_usage k JOIN information_schema.referential_constraints rc ON rc.constraint_schema=k.constraint_schema AND rc.constraint_name=k.constraint_name WHERE k.table_schema=DATABASE() AND k.table_name='conversation_protocol_messages' AND k.referenced_table_name IS NOT NULL ORDER BY k.constraint_name,k.ordinal_position")
    # Use FK semantic grouping; arbitrary MySQL auto-constraint names are discarded.
    fk_group = {}
    for constraint, column, parent, parent_column, ordinal, delete_rule in fks:
        fk_group.setdefault(constraint, []).append((ordinal, column, parent, parent_column, delete_rule))
    fk_semantics = sorted([[
        [v[1] for v in sorted(group)], group[0][2],
        [v[3] for v in sorted(group)], group[0][4]
    ] for group in fk_group.values()], key=str)
    return {"columns": cols, "indexes": indices,
            "checks": checks, "foreign_keys_semantic": fk_semantics}


def _assert_schema(conn):
    count = int(conn.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='conversation_protocol_messages'")).scalar_one())
    if count != 1:
        raise r.SafetyViolation("Protocol table missing")
    counter = conn.execute(text("SELECT column_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='conversations' AND column_name='next_timeline_sequence'")).one()
    if counter[0] != "int" or counter[1] != "NO" or str(counter[2]) != "1":
        raise r.SafetyViolation("Counter nullable/default/type mismatch")
    constraints = set(conn.execute(text("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema=DATABASE() AND table_name='conversation_protocol_messages' AND constraint_type='CHECK'")).scalars())
    if constraints != EXPECTED_CHECKS:
        raise r.SafetyViolation("Protocol CHECK names mismatch")
    enforced = conn.execute(text("SELECT enforced FROM information_schema.table_constraints WHERE table_schema=DATABASE() AND table_name='conversation_protocol_messages' AND constraint_type='CHECK'")).scalars().all()
    if len(enforced) != 5 or any(x != "YES" for x in enforced):
        raise r.SafetyViolation("Protocol CHECK is not enforced")
    rows = conn.execute(text("SELECT index_name,column_name,seq_in_index,non_unique FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='conversation_protocol_messages' ORDER BY index_name,seq_in_index")).all()
    by_index = {}
    for name, column, order, non_unique in rows:
        by_index.setdefault(name, []).append((column, non_unique))
    for name, columns in EXPECTED_UNIQUES.items():
        if by_index.get(name) != [(c, 0) for c in columns]:
            raise r.SafetyViolation(f"Unique constraint mismatch: {name}")
    for name, columns in EXPECTED_SECONDARY.items():
        if by_index.get(name) != [(c, 1) for c in columns]:
            raise r.SafetyViolation(f"Secondary index mismatch: {name}")
    schema = _capture_schema(conn)
    actual_fk = {(tuple(cols), parent, tuple(parent_cols), delete_rule)
                 for cols, parent, parent_cols, delete_rule in schema["foreign_keys_semantic"]}
    if actual_fk != EXPECTED_FK:
        raise r.SafetyViolation("Composite FK contract mismatch")
    ck_count = conn.execute(text("SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema=DATABASE() AND table_name='conversations' AND constraint_type='CHECK' AND constraint_name='ck_conversations_next_timeline_sequence' AND enforced='YES'")).scalar_one()
    r.require_zero(1 - ck_count, "Counter CHECK")
    return schema


def _assert_table_contract_after_create(conn):
    """Immediate table-level inspection before any secondary index DDL."""
    schema = _capture_schema(conn)
    actual_names = {c[0] for c in schema["columns"]}
    expected_names = {"id", "organization_id", "conversation_id", "sequence_number",
        "sender_type", "sender_agent_profile_id", "recipient_type",
        "recipient_agent_profile_id", "message_type", "payload_ciphertext",
        "payload_redacted", "data_classification", "encryption_key_ref",
        "retention_expires_at", "idempotency_key", "request_fingerprint",
        "correlation_id", "causation_id", "created_at"}
    if actual_names != expected_names:
        raise r.SafetyViolation("Protocol table column set differs from migration contract")
    actual_checks = {name for name, _clause, enforced in schema["checks"] if enforced == "YES"}
    if actual_checks != EXPECTED_CHECKS:
        raise r.SafetyViolation("Protocol CHECK contract differs from migration")
    by_index = {}
    for name, ordinal, column, non_unique in schema["indexes"]:
        by_index.setdefault(name, []).append((column, non_unique))
    for name, columns in EXPECTED_UNIQUES.items():
        if by_index.get(name) != [(col, 0) for col in columns]:
            raise r.SafetyViolation(f"Protocol unique index mismatch: {name}")
    actual_fk = {(tuple(cols), parent, tuple(parents), delete)
                 for cols, parent, parents, delete in schema["foreign_keys_semantic"]}
    if actual_fk != EXPECTED_FK:
        raise r.SafetyViolation("Protocol table FK relationships mismatch")


def _execute_approved_steps(conn, org, ids, journal):
    # Explicit statement-by-statement execution: NO RERUN on partial failure.
    # SQL DDL auto-commits in MySQL. An exception leaves partial state preserved.
    for name, statement in parse_review_sql():
        journal["current_step"] = name
        if name in ("overflow_preflight", "backfill_postcondition"):
            count = conn.execute(text(statement)).scalar_one()
            r.require_zero(int(count), name)
        else:
            conn.execute(text(statement))
            conn.commit()  # MySQL auto-commits DDL; commit is not a rollback mechanism.
        # Post-statement checks block all subsequent DDL on failure.
        if name == "backfill":
            _assert_counters(conn, org, ids)
        if name == "add_counter_check":
            found = conn.execute(text("SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema=DATABASE() AND table_name='conversations' AND constraint_name='ck_conversations_next_timeline_sequence' AND constraint_type='CHECK' AND enforced='YES'")).scalar_one()
            r.require_zero(1 - int(found), "Counter CHECK not installed")
        if name == "enforce_counter_not_null":
            row = conn.execute(text("SELECT is_nullable,column_default,column_type FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='conversations' AND column_name='next_timeline_sequence'")).one()
            if row[0] != "NO" or str(row[1]) != "1" or row[2] != "int":
                raise r.SafetyViolation("Counter NOT NULL/DEFAULT postcondition failed")
        if name == "create_protocol_table":
            _assert_table_contract_after_create(conn)
        if name.startswith("create_") and name.endswith("_time_index"):
            index = EXPECTED_SECONDARY["ix_conversation_protocol_messages_org_conversation_time" if name == "create_conversation_time_index" else "ix_conversation_protocol_messages_org_recipient_time"]
            idxname = "ix_conversation_protocol_messages_org_conversation_time" if name == "create_conversation_time_index" else "ix_conversation_protocol_messages_org_recipient_time"
            cols = conn.execute(text("SELECT column_name FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='conversation_protocol_messages' AND index_name=:n ORDER BY seq_in_index"), {"n": idxname}).scalars().all()
            if cols != index:
                raise r.SafetyViolation(f"Index {idxname} missing/wrong")
        journal["step_results"].append({"step": name, "status": "passed"})
        journal["current_step"] = None
    return journal["step_results"]


@pytest.mark.integration
@pytest.mark.skipif(not INTEGRATION_ENABLED, reason="Execution hold: independent disposable rehearsal not approved")
def test_actual_populated_state_forward_recovery(tmp_path):
    url, database, att, approval, reference = _rehearsal_inputs()
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    result = {"milestone": "M3.2.1 Phase A.2", "execution_authorization": False,
              "scope": "disposable_rehearsal_only", "database": database,
              "step_results": [], "gate_status": "failed_closed", "alembic_reconciled": False}
    try:
        # Fresh partial baseline has NO seeded conversations; preflight before writes.
        preflight = r.inspect_read_only(url, database, att)
        assert preflight["revision"] == "20261112_0011"
        with engine.begin() as conn:
            org, ids = _fresh_seed(conn)
        with engine.connect() as conn:
            # No deliberate DDL failure recovery: preserves intermediate state.
            _execute_approved_steps(conn, org, ids, result)
            _assert_counters(conn, org, ids)
            schema = _assert_schema(conn)
            if schema != reference["schema"]:
                raise r.SafetyViolation("Semantic DDL differs from successful Unicode 0012 snapshot")
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != "20261112_0011":
                raise r.SafetyViolation("Alembic revision unexpectedly changed")
            result["schema_equivalence"] = True
            result["unicode_reference_sha256"] = r.sha256_file(Path(os.environ["M321_A2_UNICODE_REFERENCE_JSON"]))
            result["reviewed_sql_sha256"] = r.sha256_file(SQL_FILE)
            result["counter_values"] = [1, 2, 8]
            result["alembic_revision"] = revision
            result["gate_status"] = "passed_disposable_only"
            conn.rollback()
    except BaseException as exc:
        # Preserve partial-DDL evidence; no auto-rollback or destructive reset.
        result["failure_type"] = type(exc).__name__
        raise
    finally:
        engine.dispose()
        destination = Path(os.environ.get("M321_A2_TEST_REPORT_PATH", str(tmp_path / "m321_disposable_rehearsal_result.json")))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert result["gate_status"] == "passed_disposable_only"
