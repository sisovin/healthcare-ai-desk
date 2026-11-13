# Healthcare AI Desk — M7: Security, QA & Production Deployment

**Status:** Review-only production-readiness blueprint.
**Execution authorization:** `false`.
**Dependencies:** M1–M6 retain their independent gates. M7 cannot certify,
override, or bypass incomplete M3/M4/M5/M6 acceptance conditions.
**Safety authority:** M2.5 remains the sole authority for high-impact approval
and external-provider egress.

## 1. Purpose

M7 defines the future security assurance, quality assurance, release, and
production-deployment discipline for Healthcare AI Desk. Its purpose is to
ensure that a deployment is authorized only when the deployed artifact,
configuration, dependencies, data-handling controls, operational runbooks, and
evidence meet an approved healthcare-safety standard.

M7 does not itself certify production readiness. Production certification
requires actual evidence from a separately approved environment and accountable
human approvals.

## 2. Release principles

| Principle | Requirement |
| --- | --- |
| Fail closed | Missing evidence, unresolved critical findings, expired approvals, or unknown configuration block promotion. |
| Traceability | Every deployable artifact, migration, configuration version, policy version, test result, and approval has a correlation/release ID. |
| Least privilege | Human users, services, CI/CD, databases, caches, vector services, providers, and observability systems receive only required permissions. |
| No safety bypass | Deployment, retry, recovery, feature flag, job, bulk action, or rollback cannot bypass M2.5, RBAC, tenant scope, or human approval. |
| Separation | Build, test, staging, and production environments have distinct credentials, data boundaries, audit trails, and change approvals. |
| Recoverability | Releases use rehearsed forward recovery, backups, health checks, and safe rollback/feature-disable procedures without destructive shared-volume resets. |

## 3. Security assurance domains

### 3.1 Identity, authorization, and tenant isolation

- Verify authentication, session/token lifecycle, MFA/administrator policy
  where applicable, RBAC, organization/project scoping, service identities,
  and break-glass governance.
- Test horizontal and vertical authorization denial across API, async workers,
  scheduled tasks, cache keys, exports, audit access, and agent workflows.
- Maintain immutable, minimal security audit records for access denials,
  privilege changes, sensitive policy decisions, and administrative actions.

### 3.2 Data protection and privacy

- Maintain a data inventory/classification, retention schedule, legal-hold
  rules, encrypted-storage/key-rotation design, and access review evidence.
- Prohibit raw patient identifiers in generic logs, queues, cache keys,
  analytics, telemetry, error traces, and external-provider payloads.
- Test PII/PHI egress denial, redaction/minimization, deletion/revocation, and
  backup/restore boundaries using synthetic data only.

### 3.3 AI, provider, and tool safety

- Confirm M2.5 owns final provider egress decisions and high-impact approval
  enforcement in every execution route.
- Test prompt injection, untrusted retrieval content, unsafe tool arguments,
  provider failure/fallback, approval expiry, retry/delegation, and egress
  mutation boundaries.
- Track provider/model/region/retention configuration, egress policy version,
  availability, rate limits, cost limits, and incident response ownership.

### 3.4 Application and supply-chain security

- Pin and scan dependencies, base images, SBOMs, source provenance, build
  attestations, secrets exposure, static analysis, and vulnerability findings.
- Set severity, ownership, remediation SLA, exception expiry, and release
  block rules. Critical or unmitigated high-severity findings block release.
- Store secrets only in approved secret-management/deployment mechanisms;
  never in source, prompts, logs, images, or test fixtures.

### 3.5 Infrastructure and resilience

- Define network segmentation, TLS, firewall/egress allowlists, database/cache
  access, Qdrant/vector boundary if later approved, backup encryption, restore
  tests, capacity, monitoring, alerting, and incident runbooks.
- Verify MySQL and Redis volumes are preserved through upgrades; no deployment
  step may reset or recreate shared volumes without an explicit approved
  recovery procedure.

## 4. QA strategy

| Test layer | Required evidence before production approval |
| --- | --- |
| Unit and contract | Deterministic tests for validation, RBAC, state transitions, safety decisions, schemas, and policy contracts. |
| Integration | Authorized synthetic-environment tests for database, outbox, cache, provider mocks, worker recovery, and API boundaries. |
| Security | SAST, dependency/image/secret scans, authorization tests, threat-model review, negative egress tests, and finding disposition. |
| Privacy/safety | Synthetic PII/PHI scenarios, disclosure controls, approval-gate tests, prompt-injection tests, and audit minimization review. |
| Reliability | Load, concurrency, lease, retry, crash/restart, backup/restore, migration/recovery, and graceful-shutdown evidence. |
| User acceptance | Approved operational scenarios, accessibility where applicable, training/runbook review, and accountable sign-off. |

Passing a unit or mock test never substitutes for the applicable integration,
security, privacy, or operational evidence.

## 5. Release artifact and configuration contract

Each candidate release must identify:

```text
release_id + source commit + signed/build artifact digest + SBOM digest
environment + deployment manifest/config digest + feature-flag set
database/Alembic revision + migration/recovery plan reference
M2.5 policy/provider configuration version + secret reference IDs
test/scan evidence IDs + known-risk/exception records + approval IDs
rollback/forward-recovery procedure + owner/on-call identity
```

Environment-specific configuration is immutable per deployment record. A change
to provider destination, policy, secret, feature flag, database revision, or
artifact requires a new release evaluation; it cannot inherit prior approval
silently.

## 6. Deployment lifecycle

```text
candidate built
  -> artifact/security/provenance verification
  -> approved synthetic staging validation
  -> release-governance review
  -> controlled production rollout
  -> health/safety/audit verification
  -> explicit production acceptance or forward recovery
```

The rollout plan must define progressive exposure, health/readiness checks,
error budget/abort criteria, feature-disable procedure, communication owner,
and incident escalation. Database migrations require their own forward-only
plan, preflight, backup/recovery evidence, and explicit authorization; a
successful application deployment does not imply migration approval.

## 7. Production monitoring and incident response

Monitor, without recording raw protected content:

- authentication/authorization denials and tenant-isolation anomalies;
- M2.5 approval, egress denial, provider/fallback, and safety-policy outcomes;
- queue/outbox backlog, lease expiry, duplicate/replay, worker health, and
  MySQL/Redis/Qdrant (if approved) availability;
- report/workflow/RAG freshness, disclosure-policy denials, and audit failures;
- latency, availability, capacity, error rate, cost, security alerts, and
  backup/restore status.

Incident response must preserve evidence, scope disclosure, contain safely,
notify accountable owners, and follow approved privacy/security obligations.
Emergency actions do not permit bypassing M2.5 approval, tenant isolation, or
patient-data protection.

## 8. Production acceptance gate

Production deployment may be considered only when all applicable entries are
independently verified and approved:

- all predecessor milestones are accepted for the proposed release scope;
- no blocked M3/M4/M5/M6 gate is silently included or enabled;
- actual governance records, security review, privacy review, clinical/operational
  ownership, and release approvers are current and accountable;
- target environment compatibility, encrypted backups, restore rehearsal,
  observability, runbooks, and rollback/forward-recovery evidence are complete;
- migration, provider, vector, worker, and external-egress changes have their
  own explicit approvals;
- critical findings are resolved; approved exceptions are time-bounded and do
  not weaken healthcare safety/privacy requirements; and
- release evidence is immutable, reviewable, and linked to the deployed digest.

## 9. Future acceptance evidence

| Test ID | Required evidence |
| --- | --- |
| M7-T01 | Release artifact/SBOM/config/policy digests and approvals match the deployed candidate. |
| M7-T02 | Cross-tenant/RBAC/safety/egress regression suite passes in authorized synthetic staging. |
| M7-T03 | Migration preflight, backup/restore, forward recovery, and volume-preservation evidence are accepted. |
| M7-T04 | Provider/worker/cache/database outage, retry, crash, and graceful-shutdown behavior is safe and audited. |
| M7-T05 | Vulnerability, secret, image, dependency, and supply-chain findings meet release-block policy. |
| M7-T06 | Monitoring, alerts, incident response, audit access, and data-retention controls are exercised. |
| M7-T07 | Rollout abort, feature disable, rollback/forward-recovery, and communication runbooks are rehearsed. |

## 10. Delivery sequence and current decision

| Package | Scope | Entry requirement |
| --- | --- | --- |
| M7.1 | Security threat model, QA plan, governance and release evidence model | Independent design review and named security/privacy/operations owners. |
| M7.2 | CI/CD, SBOM, scanning, artifact provenance, and environment configuration design | M7.1 acceptance and separate delivery-system authorization. |
| M7.3 | Authorized synthetic staging, resilience/security/privacy validation | Explicit test-environment authorization and prior milestone compatibility. |
| M7.4 | Controlled production rollout and acceptance | All applicable release gates, operational approvals, and deployment authorization. |

M7 is proposed for review-only planning. No production deployment, CI/CD
change, cloud/infrastructure mutation, secret provisioning, database migration,
provider egress, or worker activation is authorized by this document.
