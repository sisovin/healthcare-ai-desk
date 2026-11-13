# Healthcare AI Desk - M3.2.1 Phase A.2 Joint-Review Package, Revision 3

**Status: REVIEW CANDIDATE ONLY. Execution authorization is FALSE.**

No recovery DDL, database seed, Alembic reconciliation, shared changes, writer cutover, or M3.2.2 worker activation has been executed in preparing this package. The historical preserved environments at ports **34068, 34069 and 34070 must remain untouched**.

## Package contents

| Path | Intent |
| --- | --- |
| `tools/recovery/m321_forward_recovery.py` | Read-only, fail-closed inspection; rejects historical databases and ports; independently corroborates JSON Docker-inspect evidence and operator attestation. **No write or DDL code path.** |
| `tools/recovery/m321_forward_recovery.sql` | Review-only, statement-marked forward recovery SQL derived from authoritative revision `20261112_0012`. **Never run as a batch.** |
| `tests/recovery/test_m321_forward_recovery.py` | Offline unit/negative tests plus **disabled, opt-in** real populated-state rehearsal. The rehearsal is gated by a *separate* independently approved disposable-only authorization and archived successful Unicode `0012` schema snapshot. |
| `tools/recovery/m321_phase_a2_gate_evidence.json` | Evidence and provenance record. All six database gates remain `pending` until actual evidence is obtained. |
| `tools/recovery/m321_phase_a2_artifact_manifest.json` | SHA-256 manifest for the review package. It deliberately contains no self-hash and grants no execution authority. |
| `docs/M3.2.2_REVISION_1_AND_M3.2.1_JOURNAL_HARDENING_REVIEW_SUBMISSION.md` | Joint architecture and journal-hardening submission for independent review; no execution approval. |
| `docs/M3.2.2_REVISION_2_M321_JOURNAL_P0_REMEDIATION_REVIEW_SUBMISSION.md` | Latest P0 remediation submission for another review-only assessment. |
| `docs/M3.2.1_PHASE_A2_JOURNAL_REVISION_3_REVIEW_SUBMISSION.md` | P1 orphaned-ownership and simulated Windows-locking evidence submission; review only. |
| `docs/M3.2.1_PHASE_A2_JOURNAL_REVISION_4_P1_REMEDIATION_REVIEW_SUBMISSION.md` | P1 lock-metadata and epoch-monotonicity remediation submission; review only. |
| `docs/M3.2.1_PHASE_A2_DISPOSABLE_REHEARSAL_AUTHORIZATION_PROPOSAL.md` | Separate future disposable-rehearsal proposal; it grants no authority. |
| `tools/recovery/m321_step_journal.py` | Review-only journal model with exclusive writer locking, persisted `PREPARED` evidence, atomic persistence, integrity verification, immutable metadata, and full persisted-step invariant validation; it cannot execute SQL or retry unresolved work. |
| `tools/recovery/m321_step_journal_contract.md` | The required journal fields and terminal-stop contract. |
| `tests/recovery/test_m321_step_journal.py` | Offline tests for timestamps, statement fingerprints, evidence fields, and no-retry enforcement. |
| `tests/recovery/test_m322_architecture_contract_review.py` | Offline assertions for the reconciled M3.2.2 canonical routing contract. |
| `evidence/20261112_0012_protocol_message_contract.py` | Copy of authoritative user-supplied migration source for review and SHA-256 provenance. |
| `pytest.ini` | Declares the `integration` marker. |

## What was actually verified for this submission

- Static Python compilation of the recovery inspector, step journal, and both offline test modules.
- Offline pytest checks of pinned target allow-list, refusal cases for invalid partial state, nonexistent/invalid attestation, attempted continuation after a nonzero gate result, exact statement-marker order, evidence retaining authorization `false`, and terminal `STOP_NO_RETRY` journal behavior.
- No MySQL server and no preserved or shared database were connected to or modified.

Static checks are **not** evidence that the MySQL DDL works, that the disposable fixture can seed successfully on your exact revision `0011`, or that the SQL is DDL-equivalent to the successful Unicode run.

## Follow-up gates (not approved here)

1. Independently create a **new** Docker MySQL 8.4 container named `had-m321-a2-*`, bind only `127.0.0.1:34071->3306`, and use `tmpfs` storage at `/var/lib/mysql`. Provision the new database as `had_m321_a2_<12lowerhex>` and the application migrations **through `20261112_0011` only**; inject only the documented nullable counter partial state. Both actions require independent rehearsal authorization before execution.
2. Independently capture an unedited `docker inspect` JSON record, a fresh attestation identifying operator and different verifier, writer shutdown, transaction drain, MySQL server UUID, and the inspected file hash.
3. Independently export the successful Unicode `0012` normalized schema snapshot to a JSON file with `provenance.source_environment = "successful_0012_unicode_rehearsal"` and a `schema` object matching `_capture_schema()`. No preserved DB query is performed by this package. If archival evidence is unavailable, the schema-equivalence gate stays pending.
4. Have an independent reviewer approve a **disposable-only** rehearsal in a separate JSON authorization file referencing database, container ID, exact SQL SHA-256, reviewer and expiry. **No such authorization is included**; the review gate template explicitly records `execution_authorization: false`.
5. After approval (not now), run the isolated tests and capture step-by-step evidence. The integration test rejects already populated databases, seeds an organization, user, project, then zero/one/seven-message conversations; verifies counters 1/2/8, the CHECKs, scoped FKs, uniqueness, index order, schema-equivalence snapshot and unchanged Alembic revision `0011`. Any mismatch stops subsequent statements and records partial progress. **Never rerun on a partial failure**.
6. Submit actual log/evidence artifacts to another independent joint review. A disposable success **does not** authorize the preserved database or any shared write/cutover.

## Offline checks (safe now)

From this package's root:

```powershell
python -m py_compile tools/recovery/m321_forward_recovery.py tools/recovery/m321_step_journal.py tests/recovery/test_m321_forward_recovery.py tests/recovery/test_m321_step_journal.py
python -m pytest -q tests/recovery/test_m321_forward_recovery.py tests/recovery/test_m321_step_journal.py -m "not integration"
python -m pytest -q -p no:cacheprovider tests/recovery/test_m321_step_journal.py tests/recovery/test_m322_architecture_contract_review.py
```

**Do not set** `M321_A2_APPROVED_DISPOSABLE_REHEARSAL=1` during the current hold. The integration test is skipped by default.

## Important implementation caveats for reviewer

- `20261112_0012` declares its three composite FKs without explicit names. The review SQL therefore uses unnamed FKs; semantic comparison strips generated names. Exact MySQL engine-generated DDL still requires independent reference evidence.
- The recovered table, check names and unique indexes are derived from the latest user-supplied `0012` revision, but have not been executed on MySQL here.
- The opt-in synthetic seeding fixture assumes actual `0011` core table and message-column shapes; if they differ, it **fails closed**. Do not make ad-hoc schema changes on the test target to force a pass.
- The `docker inspect` + operator JSON documents are reviewable provenance, not cryptographic proof of physical isolation. An independent reviewer must corroborate them.
- The inspection login needs the MySQL `PROCESS` privilege to verify active connections and the InnoDB transaction list; login should otherwise have minimum read permissions. Seed/recovery rehearsal credentials must be separately scoped to the new disposable database only.
- SQL DDL is nontransactional in MySQL. Neither a test failure nor a Python `rollback()` reverses earlier committed DDL. Stop and preserve evidence; do **not** execute the migration or an `alembic stamp` on partial state.
- The recovery SQL uses literal `CREATE TABLE ... DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`; compare physical table semantics with the archived successful Unicode run before any approval.
- The `m321_phase_a2_gate_evidence.json` is prepared for submission and represents **static** results only; the six live-data acceptance gates remain pending.
