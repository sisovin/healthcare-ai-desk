# Healthcare AI Desk — M6: Reporting & Analytics

**Status:** Review-only architecture blueprint.
**Execution authorization:** `false`.
**Dependencies:** M1–M2.5 remain authoritative. M3–M5 retain their individual
gates; M6 does not override or unblock them.
**Safety authority:** M2.5 remains the sole authority for high-impact approval
and external-provider egress.

## 1. Purpose

M6 defines a future reporting and analytics capability for healthcare
operations: tenant-scoped dashboards, scheduled reports, data-quality views,
workflow performance, agent/safety observability, and approved aggregate
program indicators. It is intended to support accountable decision-making, not
to make clinical decisions or expose patient-identifying information.

Analytics are descriptive unless a separately approved workflow interprets or
acts on them. A chart, trend, score, forecast, or generated narrative cannot
authorize clinical action, alter a care plan, or override M2.5/M3/M4/M5 gates.

## 2. Scope boundaries

M6 may eventually provide:

- organization/project-scoped operational dashboards and exports;
- aggregate counts, trends, timeliness, workload, queue, and workflow metrics;
- data-quality exceptions, lineage, completeness, and freshness indicators;
- audit/safety observability with minimal, non-sensitive metadata;
- approved scheduled report drafts and human-reviewed narrative summaries.

M6 must not:

- expose raw patient records, direct identifiers, rare-cell results, or
  re-identifiable small aggregates through a dashboard/export;
- derive or present a clinical diagnosis, triage decision, treatment advice, or
  patient-specific risk recommendation as automated authority;
- aggregate across organizations/projects without an explicit server-authorized
  governance scope;
- transmit report data, prompts, narratives, or analytics extracts externally
  without M2.5 egress evaluation and applicable authorization;
- use reports, metrics, or AI summaries to bypass human approval.

## 3. Architectural principles

| Concern | Decision |
| --- | --- |
| Authoritative facts | MySQL remains authoritative for operational source facts and audit references. Derived views are rebuildable. |
| Tenant isolation | Every query, cache key, materialization, export, and scheduled delivery carries server-derived organization/project/purpose scope. |
| Data minimization | Prefer approved aggregate metrics and opaque identifiers. Raw protected content never belongs in generic analytics logs or cache keys. |
| Privacy | Suppress, bucket, round, or deny small/re-identifiable cells according to approved policy; policy evaluation is server-owned. |
| Lineage | Every metric/report version records source scope, query/definition version, refresh time, data freshness, policy decision, and provenance. |
| Egress | External BI, email, storage, LLM summaries, telemetry, or provider routes require M2.5 policy/egress controls. |
| Delivery | MySQL state/audit/outbox commits atomically; Redis or future schedulers accelerate recoverable delivery only. |

## 4. Data classification and disclosure control

M6 uses a server-owned classification before a metric, visual, export, or
narrative is generated:

| Class | Permitted initial handling |
| --- | --- |
| Operational aggregate | Eligible after tenant/RBAC/purpose and disclosure-policy checks. |
| Project-restricted aggregate | Eligible only for active authorized project scope. |
| Sensitive aggregate | Eligible only with approved disclosure rules, minimum-cell controls, and authorized role/purpose. |
| Patient-restricted/raw data | Deny by default from generic analytics and exports. Separate protected workflow required. |

Disclosure policy must consider denominator, minimum cell size, complementary
suppression, time/location granularity, rare categories, joining/linkage risk,
and export format. A technically aggregated result is not automatically safe to
disclose. If policy cannot decide safely, M6 returns a bounded denial rather
than a partially redacted result.

## 5. Request, query, and export contract

The server constructs an immutable `AnalyticsAuthorizationContext` from the
authenticated principal and authoritative scope:

```text
principal_id + principal_type
organization_id + authorized project set
purpose_of_use + role/clearance/assignment generation
report_definition/version + requested dimensions/measures
time window + disclosure policy/version
request_id + correlation_id
```

Client parameters can select only an allow-listed report definition and
validated dimensions within this context. They cannot provide a tenant ID,
arbitrary SQL, unbounded date range, protected field name, cross-tenant join,
or disclosure-policy override.

Before response/export finalization, the service rechecks current authorization,
report publication, source-data lifecycle, disclosure result, and export
destination. A revoked role/assignment or changed disclosure policy prevents
new output. Cached aggregates never bypass the final disclosure check.

## 6. Metric definition and lineage contract

Metrics are versioned, reviewed definitions—not ad hoc transformations.
Every published metric/report definition requires:

```text
metric/report definition ID and version
approved measures, dimensions, filters, and permitted granularity
source entity/version references and tenant/project scope rule
data-quality/freshness rule and calculation/semantic version
disclosure-control policy and threshold version
owner, reviewer, approval/effective/expiry dates
```

Historical reports retain their definition/version and refresh provenance. A
definition change creates a new version; it does not silently rewrite a prior
report. Backfills/recomputations are explicitly labelled and auditable.

## 7. Scheduled reporting and generated narratives

Scheduled report creation, recipient selection, export, and delivery are
separate actions. The scheduler verifies recipient authorization, report scope,
disclosure policy, freshness, and destination policy immediately before
delivery. A stale schedule cannot continue delivering after scope revocation.

AI-generated narrative summaries are drafts. If a summary uses an external
provider, M2.5 evaluates the final minimized aggregate payload and destination
at the egress boundary. The report service cannot select a less-safe fallback,
reuse a denied decision, or send raw patient data to obtain a narrative.

High-impact operational actions suggested by analytics enter the existing
human-approval workflow; M6 has no approval authority.

## 8. Proposed authoritative entities (design only)

| Entity | Core invariant |
| --- | --- |
| `report_definitions` | Tenant-scoped, versioned, published only after authorized review; no arbitrary SQL field. |
| `metric_definitions` | Immutable published calculation/disclosure versions with source lineage. |
| `report_runs` | Organization/project/purpose scope, report version, refresh snapshot, lifecycle, idempotency/correlation IDs. |
| `report_artifacts` | Access-controlled output reference, classification, retention/expiry, content hash, destination decision reference. |
| `analytics_export_requests` | Server-owned scope, disclosure result, recipient/destination policy, approval state where needed. |
| `analytics_refresh_receipts` | Idempotent refresh/materialization receipt with source/freshness and calculation version. |
| `analytics_audit_logs` | Minimal actor, scope, definition/version, disclosure/egress decision, and sanitized outcome metadata. |

All future relations use tenant-scoped composite foreign keys and unique keys.
Any future schema is additive and forward-only, subject to a separate approved
schema/rehearsal gate; no existing MySQL/Redis volume may be reset or deleted.

## 9. Reliability, quality, and recovery

1. Persist report/export state, audit event, and outbox intent atomically.
2. Treat scheduled refresh/export delivery as at-least-once; use idempotency
   receipts to prevent duplicate artifact generation or distribution.
3. Label stale, incomplete, late, failed, or backfilled data; do not silently
   substitute an incomplete result for a complete report.
4. Recheck authorization and disclosure policy after retry/recovery; a retry
   cannot retain a previously valid scope after revocation.
5. Preserve failure diagnostics as minimal error codes and correlation IDs, not
   raw data extracts, credentials, or patient information.

## 10. Future acceptance evidence

| Test ID | Required evidence |
| --- | --- |
| M6-T01 | Cross-organization/project reports, caches, exports, schedules, and audit reads are denied. |
| M6-T02 | Small-cell, linkage, granularity, and policy-change cases suppress or deny unsafe disclosure. |
| M6-T03 | Definition/version lineage, freshness, backfill, and data-quality labels are complete and immutable. |
| M6-T04 | Duplicate refresh/export/schedule delivery and crash recovery produce one authorized logical artifact/delivery. |
| M6-T05 | Role, assignment, destination, or policy revocation between generation and delivery prevents disclosure. |
| M6-T06 | External narrative/BI/export egress is denied or minimized according to M2.5; no weaker fallback occurs. |
| M6-T07 | Analytics suggestions, RAG content, and prompt-injection text cannot invoke tools, approval, or high-impact action. |
| M6-T08 | Retention, legal hold, export deletion, audit lineage, and operator recovery remain consistent. |

All tests require synthetic data and separately authorized execution evidence.

## 11. Delivery sequence and gates

| Package | Scope | Entry requirement |
| --- | --- | --- |
| M6.1 | Reporting/privacy/security contract and metric governance | Independent design review and accountable governance owners. |
| M6.2 | Forward-only report/metric metadata schema and scoped repositories | Approved governance records, real schema compatibility review, disposable-only authorization. |
| M6.3 | Refresh, materialization, export, and scheduling reliability | M6.2 acceptance and failure/recovery design approval. |
| M6.4 | Dashboards, report APIs, and reviewed narrative integration | M6.3 safety/reliability evidence and privacy/governance acceptance. |
| M6.5 | End-to-end analytics acceptance and operational readiness | Full synthetic security, disclosure, recovery, audit, and independent acceptance evidence. |

## 12. Current decision

M6 is proposed for review-only planning. No analytics schema, materialization,
dashboard, export, scheduler, external BI/provider integration, or operational
action is authorized by this document.
