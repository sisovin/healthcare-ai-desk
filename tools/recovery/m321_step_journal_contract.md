# M3.2.1 Phase A.2 - Review-Only Journal Contract, Revision 3

**Execution authorization:** `false`. This artifact cannot execute SQL, Alembic, Docker, or database actions.

## Exclusive writer contract

A future separately authorized runner must create a `JournalMutation` with a `JournalFileLock` before it reads, prepares, writes, reloads, or verifies the journal. The lock remains held across the complete read/verify → mutation → atomic write → reload/verify interval.

The lock uses a fixed one-byte OS lock file opened without append mode and a separate atomic JSON metadata sidecar. This prevents Windows append-mode NUL/JSON corruption. The sidecar records `rehearsal_id`, journal path, instance ID, and unpredictable run nonce. Lock contention, lock I/O failure, lock-path substitution, an ambiguous/stale `held` record, invalid metadata, or an unsupported OS locking operation fails closed. There is no automatic stale-lock break. A lock does not grant execution authority.

## Monotonic step lifecycle

Every future statement has an append-only two-record lifecycle:

```text
PREPARED → PASSED
PREPARED → STOP_NO_RETRY
```

`prepare_and_persist()` writes and reload-verifies `PREPARED` before a separately approved runner could start a statement. It records the statement fingerprint, reviewed SQL hash, disposable target identity, operator-approval reference, observed passing preconditions, and before-snapshot SHA-256. The first durable write must contain exactly one `PREPARED` record; a fresh `PREPARED` + `PASSED` batch is rejected. Every later durable write appends exactly one valid lifecycle record.

Only the one unresolved final `PREPARED` record may receive an outcome. `pass_and_persist()` requires all observed postconditions to pass and records the after-snapshot SHA-256. `stop_and_persist()` preserves safe failed-observation evidence, nonzero exit code, and reason code, then permanently blocks continuation. A restart with unresolved `PREPARED` is evidence for independent reconciliation, not authority to retry.

## Orphaned ownership reconciliation

Every `PREPARED` record contains immutable ownership evidence: a positive
epoch, instance ID, and run nonce. If a mutation session finds an unresolved
`PREPARED` owned by a different instance/run epoch, it is fail-closed. It may
not record `PASSED`, `STOP_NO_RETRY`, a replacement `PREPARED`, or retry a
statement.

Only a reconciliation-only mutation may append `RECONCILED` for that exact
prepared step. It must include a structured independent authorization with the
prepared step ID, exact prior ownership, reviewer identity, approval
reference, SHA-256 evidence reference, and passing observed reconciliation
assertions. The new owner epoch must be strictly greater than the prior epoch,
and any later outcome must name that reconciled owner. These links are
revalidated during reconciliation creation, before persistence, and on reload.

`RECONCILED` records evidence only; it never executes or retries SQL. This
module cannot prove that an external reviewer is genuine. A future separately
authorized runner must validate the external authority before requesting
reconciliation. A matching original instance/run nonce may finish its own
persisted step; every other identity requires reconciliation.

## Persistence and integrity

The journal uses canonical JSON and SHA-256 integrity metadata. Each mutation is built in an immutable candidate copy; persistence writes and fsyncs a same-directory temporary file, atomically replaces the target, then reloads and verifies the sealed journal while the exclusive lock remains held. The in-memory session is replaced only after that verification succeeds.

All saved entries are revalidated at persistence/read time. A `PASSED` entry with any failed observed assertion, an invalid snapshot/fingerprint, a malformed terminal outcome, a status/step-count mismatch, an illegal status transition, a changed immutable metadata field, or a non-append-only history is rejected. Any mutation, write, reload, integrity, or lock failure fault-latches the current `JournalMutation`; that session cannot prepare or finalize another step.

Persisted metadata is immutable except the append-only `steps`, top-level workflow status, terminal record, and regenerated integrity data. Legal journal states are:

```text
PENDING_REVIEW → PREPARED → IN_PROGRESS_REVIEW_ONLY → PREPARED ...
PREPARED → STOP_NO_RETRY
STOP_NO_RETRY → STOP_NO_RETRY only (byte-equivalent idempotent persistence)
```

## Non-authorization

This contract does not authorize recovery DDL, Alembic reconciliation, shared environment changes, writer cutover, M3.2.2 workers, external LLM patient-data egress, or any M2.5 approval bypass. All six M3.2.1 Phase A.2 live gates remain independently pending.

## Offline Windows locking evidence and remaining boundary

The offline regression suite simulates the Windows `msvcrt` byte-lock call and
asserts that the fixed lock file receives only one NUL lock byte while JSON is
written to the separate `.lock.meta` sidecar. It also checks non-append lock
open modes. This is not evidence of native multi-process contention, crash
leftovers, power-loss behavior, antivirus interference, or Windows filesystem
durability. Those remain separately authorized disposable-environment work.
An existing fixed-byte lock file with no `.lock.meta` is also ambiguous and is
rejected. Ambiguous or stale `held` metadata must never be broken
automatically.
