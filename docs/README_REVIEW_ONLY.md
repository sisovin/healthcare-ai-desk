# Healthcare AI Desk — M3.2.1 Phase A.2: Step-Journal Review Candidate

**STATUS: REVIEW ONLY — EXECUTION AUTHORIZATION = FALSE.**

This deliverable adds a durable, append-only **statement journal** to the previous
review-only recovery package. **No database, Docker, or recovery command was
executed while preparing this package.** Do not execute DDL, `alembic upgrade`,
`alembic stamp`, writer cutover, or M3.2.2 worker activation under the present hold.

## Files

| Relative path | Scope |
| --- | --- |
| `tools/recovery/m321_forward_recovery.py` | Previously generated *read-only* inspector; no DDL code path; strict new-disposable identity gates |
| `tools/recovery/m321_forward_recovery.sql` | Review-only statement-marked SQL derived from authoritative `0012`; **do not execute** |
| `tools/recovery/m321_step_journal.py` | **New** fsync-backed JSONL journal; no SQL connection or executor |
| `tests/recovery/test_m321_forward_recovery.py` | Existing comprehensive offline tests plus opt-in integration rehearsal, instrumented to journal each future statement if separately approved |
| `tests/recovery/test_m321_step_journal.py` | **New** offline journal behavior and negative-case tests |
| `tools/recovery/m321_phase_a2_gate_evidence.json` | Updated unpopulated machine-readable gate evidence with journal fields |
| `evidence/20261112_0012_protocol_message_contract.py` | Authoritative user-uploaded migration source |
| `evidence/user_uploaded/*` | **Unmodified latest user-uploaded evidence/test** for traceability; not executed |
| `evidence/offline_static_checks.txt` | Only real check output; offline tests, not a database rehearsal |
| `evidence/STEP_JOURNAL_CONTRACT.md` | Journal contract and failure handling |
| `SHA256SUMS.txt` | Hashes of packaged source/evidence files |

## Exact eight-step statement journal

1. `overflow_preflight` (SELECT expected zero)
2. `backfill` (UPDATE counters)
3. `backfill_postcondition` (SELECT expected zero)
4. `add_counter_check` (ALTER)
5. `enforce_counter_not_null` (ALTER)
6. `create_protocol_table` (CREATE TABLE)
7. `create_conversation_time_index` (CREATE INDEX)
8. `create_recipient_time_index` (CREATE INDEX)

Each future authorized statement emits `statement_started` (UTC timestamp,
statement SHA-256, checked preconditions, before-schema snapshot hash, pending
postconditions, unset exit code); then either `statement_passed` (UTC timestamp,
postcondition evidence, after-schema hash, exit code 0), or `statement_failed`
(nonzero exit code, categorized failure, after-schema reference if captured)
**followed by a terminal `STOP_NO_RETRY` event**. A failure in journaling itself
must stop the runner. Hash-chain verification detects edited/truncated events.
Existing journal file is never opened for append or restart.

If an exception or process crash prevents a terminal record from being written,
`verify_chain` rejects the unsealed journal as **indeterminate/STOP/NO RETRY**.
MySQL DDL may auto-commit; no automatic rollback, cleanup, replay or stamping
is attempted. A full eight-step success is marked
`journal_completed_disposable_only`; it is **not** execution authorization.

## Precise limits of verification

The only tests executed for this package were Python syntax compilation and
**offline unit tests**. The opt-in `@pytest.mark.integration` test was **excluded**.
No Docker instance identity, MySQL 8.4, actual counter values `1,2,8`, table
schema, successful Unicode reference equivalence, or Alembic state was verified
in this turn. The six acceptance gates remain `pending`.

The existing integration fixture still requires independent approval, strict
new-disposable-only identity, transaction-drain attestation, fresh seed,
exact SQL fingerprint, archived Unicode reference, and an expiry-limited
reviewer authorization. Its journal file is created **only after those gates**
are evaluated and before statement execution. Do **not** activate this test
under the current hold. No approval document is provided in this package.

### Static-check command (safe, runs no database)

From the package root:

```powershell
python -m py_compile tools/recovery/m321_forward_recovery.py tools/recovery/m321_step_journal.py tests/recovery/test_m321_forward_recovery.py tests/recovery/test_m321_step_journal.py
python -m pytest -q tests/recovery -m "not integration" --disable-warnings
```

### Docker Desktop preparation (read-only only; your own machine)

Commands such as `docker ps --no-trunc` and `docker inspect <new-disposable-container-id>`
can collect independent identity evidence. Do not create, seed, migrate, or
run a recovery against a preserved/shared environment. A future disposable
instance must be independently verified: loopback published host port `34071`,
internal MySQL `3306`, new database name matching `had_m321_a2_<12 lowercase hex>`,
MySQL `8.4.x`, `/var/lib/mysql` on tmpfs, no persistent mounts, correct image,
rev `20261112_0011`, and approved shutdown/drain attestations. The historical
ports `34068`, `34069`, `34070` are forbidden targets.

## Known reviewer issues and boundaries

- The **latest user-uploaded** static test asserts that the string
  `conversation_protocol_messages_ibfk_1` appears in the authoritative `0012`
  migration. It does not: the `0012` FK declarations are **unnamed**. The
  active packaged offline suite uses AST/structural checks instead of assuming
  engine-generated FK names. The unmodified latest upload is preserved under
  `evidence/user_uploaded/` for provenance.
- Journal evidence is not independent proof that `SHOW CREATE TABLE` matches
  the successful Unicode rehearsal. An archived, independently validated
  normalized schema reference is still required.
- Journal timestamps and hash chaining alone do not attest to Docker isolation
  or reviewer authorization. Human and external-system evidence remains required.
- The journal is additive to the opted-in test path, not a license to run it.
- No **preserved** 34068/34069/34070 database should be queried or modified
  under the current hold.

## Joint-review decision

**Submission: review candidate. All six Phase A.2 live gates are pending.
No recovery execution or environment change authorized.**
