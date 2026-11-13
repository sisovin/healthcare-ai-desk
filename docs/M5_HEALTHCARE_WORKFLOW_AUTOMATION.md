# Healthcare AI Desk — M5: Healthcare Workflow Automation

**Status:** Review-only architecture blueprint.
**Execution authorization:** `false`.
**Dependencies:** M1–M2.5 remain authoritative. M3 and M4 retain their own
acceptance gates; M5 does not override or unblock them.
**Safety authority:** M2.5 remains the sole authority for high-impact approval
and external-provider egress.

## 1. Purpose

M5 defines a future workflow-automation layer for repeatable healthcare
operational processes: intake routing, completeness checks, task coordination,
reminders, escalation, reporting preparation, and approved knowledge-assisted
workflows. It is intended to reduce administrative burden while preserving
human clinical and operational accountability.

Automation is not clinical autonomy. A workflow result is a recommendation,
draft, notification candidate, or queued task unless an explicitly authorized
human/system action performs the next step.

## 2. Scope boundaries

M5 may eventually orchestrate low-risk, policy-approved actions such as:

- routing a de-identified request to an eligible team or agent;
- checking required non-patient-specific workflow fields;
- creating a draft report, checklist, or follow-up task;
- tracking due dates, retries, and assigned ownership;
- requesting human review when policy, data classification, or workflow rules
  require it.

M5 must not autonomously:

- diagnose, triage, prescribe, refer, discharge, or change a patient care plan;
- send patient-identifying data to an external provider without the required
  M2.5 policy decision, data protection, and authorization;
- approve its own high-impact action or override a rejection/expiry;
- bypass M2.5 via retry, delegation, fallback, scheduled job, or bulk action;
- treat retrieved RAG content or an agent message as execution authority.

## 3. Core architecture

```text
Authenticated User / Authorized System Event
  -> Server-owned workflow request and tenant/RBAC validation
  -> Workflow policy classification and M2.5 safety/egress decision
  -> Durable MySQL workflow state + audit + transactional outbox
  -> Recoverable delivery/coordination through Redis acceleration
  -> Eligible human, service, supervisor, or agent task
  -> Human approval gate where required
  -> Authoritative outcome, audit, and notification/retry state
```

MySQL remains the authoritative workflow store. Redis and any future scheduler
are recoverable accelerators, not authorities for workflow state, eligibility,
approval, or completion. At-least-once delivery requires idempotent consumers
and explicit side-effect deduplication.

## 4. Workflow types and risk classification

| Workflow class | Examples | Initial automation disposition |
| --- | --- | --- |
| Administrative low risk | Reminder drafts, report assembly, SOP checklists | May be automated after tenant/RBAC/policy checks. |
| Operational medium risk | Assignment suggestions, escalation proposals, data-quality exceptions | Create a reviewable draft/task; human confirmation may be required by policy. |
| High impact | Clinical advice, referral, medication, patient record change, external communication, access/financial changes | Enter `waiting_approval`; M2.5/human authority required before runnable execution. |
| Restricted data | Patient-identifying or patient-restricted content | Deny by default from generic automation and external egress; separate approved workflow required. |

Risk classification is server-owned and immutable for an execution attempt. A
client, agent, or workflow definition cannot lower the classification.

## 5. Workflow lifecycle and concurrency

The future authoritative lifecycle is:

```text
draft -> validated -> queued -> running
                     -> waiting_dependency
                     -> waiting_approval
                     -> paused
running -> completed | failed | cancelled
waiting_approval -> queued | rejected | expired | cancelled
```

Only server-side services transition `running` or terminal states. State
updates use optimistic concurrency, immutable correlation/causation IDs, and
idempotency keys. A request replay returns the original result only when the
canonical validated intent and server-derived scope match; otherwise it returns
a conflict.

Workflow retries preserve the original safety classification and must obtain a
fresh M2.5 egress/approval decision whenever the payload, destination, provider,
operation, or authorization state changes.

## 6. Human approval and safety contract

For high-impact work, M5 creates no runnable execution until M2.5 evaluates the
final intended operation and the durable human-approval workflow has approved
it. The approval record binds the authoritative actor, organization/project,
operation, risk classification, canonical payload representation, expiry, and
audit correlation.

The workflow engine, supervisor, scheduler, agent, worker, and retry handler
have no API or permission to approve on behalf of a human. A stale, rejected,
expired, or ambiguous approval produces a fail-closed workflow state.

## 7. Data protection and knowledge use

- Organization/project scope, purpose, RBAC, and assignment checks occur before
  a workflow exposes data or creates work.
- Raw patient data are excluded from generic workflow event payloads, Redis,
  telemetry, and audit metadata. Use opaque references and authoritative
  access-controlled retrieval where a separately approved protected workflow
  permits it.
- External embeddings, LLM requests, reranking, remote vector services, and
  outbound communications require M2.5 egress policy and data minimization.
- M4 knowledge retrieval, if later authorized, supplies cited context only.
  It cannot approve actions, change routing policy, or override workflow gates.
- Audit data remain minimal: actor, action, purpose, scope, policy/approval
  decision IDs, workflow/version IDs, correlation IDs, and sanitized outcomes.

## 8. Proposed authoritative entities (design only)

| Entity | Core invariant |
| --- | --- |
| `workflow_definitions` | Tenant-scoped, versioned, published only after authorized review; immutable published version. |
| `workflow_instances` | Server-owned lifecycle/state version, organization/project scope, correlation ID, risk classification, idempotency key. |
| `workflow_steps` | Deterministic ordinal/dependency graph, assigned actor/agent, status, attempt and safety state. |
| `workflow_step_dependencies` | Composite tenant FKs and unique edge; cycle-free validated graph. |
| `workflow_approval_bindings` | References M2.5/human approval authority; cannot represent a self-approval. |
| `workflow_action_receipts` | Tenant-scoped idempotency proof for any side effect. |
| `workflow_audit_logs` | Append-only minimal event metadata; no raw protected payload. |

Any future schema is additive and forward-only, begins only after its own
approved design/rehearsal gate, and must not modify existing MySQL or Redis
volumes destructively.

## 9. Reliability and recovery

1. Persist workflow state, audit event, and outbox intent in one MySQL
   transaction.
2. Deliver work at least once; consumer-side unique receipts prevent duplicate
   side effects.
3. Lease work with expiry/fencing so old workers cannot complete a reassigned
   attempt.
4. On crash/restart, reconcile authoritative state before retrying. Never infer
   successful external side effects from an absent acknowledgement.
5. Failed approval, egress, agent, provider, or scheduling paths retain their
   safety gate; recovery cannot downgrade risk or bypass review.

## 10. Future acceptance evidence

| Test ID | Required evidence |
| --- | --- |
| M5-T01 | Cross-organization/project workflow creation, read, action, and audit access are denied. |
| M5-T02 | Duplicate submission, outbox replay, consumer retry, and crash recovery create one logical side effect. |
| M5-T03 | Concurrent state changes and leases yield one valid authoritative transition. |
| M5-T04 | High-impact, retry, fallback, delegation, and scheduled execution cannot bypass M2.5 approval. |
| M5-T05 | PII/PHI egress and external provider fallback are denied/held according to M2.5 policy. |
| M5-T06 | Revoked assignment, expired approval, or disabled workflow definition prevents execution. |
| M5-T07 | RAG/prompt-injection content cannot alter workflow policy or invoke unauthorized actions. |
| M5-T08 | Audit, retention, legal-hold, and operator recovery records remain complete and minimally disclosed. |

No test may be reported as passed without actual execution evidence from an
authorized environment using synthetic data only.

## 11. Delivery sequence and gates

| Package | Scope | Entry requirement |
| --- | --- | --- |
| M5.1 | Workflow security/architecture contract and governance model | Independent design review; M2.5/M3/M4 dependencies documented. |
| M5.2 | Forward-only workflow metadata schema and scoped repositories | Approved governance records, real schema compatibility review, disposable-only authorization. |
| M5.3 | Durable orchestration, outbox, scheduler, and approval bindings | M5.2 acceptance plus failure/recovery design approval. |
| M5.4 | Healthcare workflow templates and human-facing APIs | M5.3 safety/reliability evidence and clinical/operational ownership approval. |
| M5.5 | End-to-end acceptance and operational readiness | Full synthetic integration, security, recovery, audit, and independent acceptance evidence. |

M5 does not begin implementation merely because an earlier blueprint exists.
Each package requires separate authorization and must retain the active M3/M4
gates.

## 12. Current decision

M5 is proposed for review-only planning. No workflow automation, schema change,
scheduler, worker, external provider call, or healthcare operational action is
authorized by this document.
