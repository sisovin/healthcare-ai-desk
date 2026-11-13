# Healthcare AI Desk — M4-GOV-03 M2.5 Interface Compatibility Gap Analysis

**Date:** 2026-11-13
**Repository revision inspected:** `c373c74bae09e92d72b990c58ea9bd6d6dbaee40`
**Scope:** Offline static source/interface analysis only.
**Execution authorization:** `false`.
**Decision:** **M4-GOV-03 remains `PENDING` / `DRAFT`; M4.2/M4.3 remain
BLOCKED.**

## 1. Purpose and non-claim

This analysis compares the current checked-in M2.5 gateway/safety source with
the M4.1 Revision 4 requirement for M2.5-owned atomic egress attempts. It does
not test an API, contact a provider, inspect deployment configuration, or
authorize a code change. Static source absence is a compatibility gap, not a
claim that a live deployment is insecure.

M4 must not create a parallel approval, provider, egress, or recovery
authority. Any capability required by M4 must be designed, approved, and owned
within M2.5 or an explicitly M2.5-authorized interface.

## 2. Evidence inventory

| Artifact | SHA-256 | Static evidence |
| --- | --- | --- |
| `apps/api/app/services/safety_policy.py` | `c92e16f7a98bfc51acd4b7148fab81100c8581ec40cd28cc4bf92719c72e9c90` | Local/external provider classification, potential patient-identifier denial for external providers, and high-impact approval requirement. |
| `apps/api/app/services/llm_gateway.py` | `93dbf21927f73f3a2f59944d71bea3eb77bf5368573aef6f2b02adc754f2264e` | Final pre-provider safety call, `LLMRequest`, route selection, availability fallback, and limited audit sink. |
| `apps/api/app/services/llm_providers.py` | `d51c8de2347d0e2983bf0b49319651ff0a209757494bb2c9d28662530d66c1c1` | Injected OpenAI, Anthropic, and Ollama transports/adapters. |
| `apps/api/tests/test_m25_llm_gateway_and_tools.py` | `cbc1cc80c1acbea13c03e22e1f8add61b797773ea020927df62e1c9233daabdc` | Mock-based gateway, provider, approval, patient-data, and tool-boundary tests. |
| `docs/M2.5_IMPLEMENTATION_PACKAGE.md` | `4bbfa5f73768d62a72a585917c7f0a3bd6a0a7474695c2ce781945025020e922` | M2.5 design authority for final egress and high-impact approval. |
| `docs/M4.1_SECURITY_AND_ARCHITECTURE_CONTRACT_REVISION_4.md` | `080f5f634cce27072cc95a9f300f9ef555a01564f095b5dc23432fad10157dc8` | Required M4 exact-attempt, `CONSUMED` recovery, and no-old-decision-resend contract. |

The inspected worktree had no uncommitted changes beneath `apps/api`; current
uncommitted files were documentation artifacts. This does not verify any live
deployment state.

## 3. Current static M2.5 interface shape

The existing `LLMRequest` carries message content, task type, requested
capabilities, optional preferred provider, and a boolean `approval_granted`.
`LLMGateway.complete()` chooses a route, invokes `evaluate_execution_safety()`
before each provider attempt, rejects high-impact work when that boolean is
false, and retries another eligible provider after `ProviderUnavailableError`.

`SafetyDecision` records only potential identifier presence, whether approval
is required, and a reason. Existing audit events record limited provider/model,
token, cost, and fallback information. The mocked tests prove current behavior
only; they do not prove a durable M2.5 service/API contract.

## 4. Revision 4 compatibility matrix

| Revision 4 requirement | Existing static evidence | Compatibility disposition | Required M2.5-owned follow-up |
| --- | --- | --- | --- |
| Immutable `egress_attempt_id` bound to operation, canonical/redacted payload hashes, principal/purpose, provider/endpoint/model/region/retention, policy version and expiry | No corresponding field or durable record in `LLMRequest`, `SafetyDecision`, gateway, or provider adapter. | **Absent / incompatible until designed.** | Define a versioned decision/attempt request and response contract with exact binding and expiry. |
| Atomic `NOT_SENT → RESERVED → CONSUMED` single-use transition | Gateway makes an in-process safety decision then invokes a provider; no durable attempt-state API is present. | **Absent / incompatible until designed.** | M2.5 owner defines durable authoritative attempt storage and conditional reservation/consumption operation. |
| M2.5-owned `CONSUMED` crash reconciliation to `UNCERTAIN` | No attempt/outcome state, sender lease, reconciler, provider receipt, or uncertainty state is present in inspected source. | **Absent / incompatible until designed.** | Define ownership, recovery schedule/lease, admissible provider outcome evidence, and no-reuse rule. |
| No old-decision resend after unknown provider outcome | Current availability fallback retries alternate eligible route; each attempt reruns current basic safety policy but has no exact decision identity. | **Unverified and contractually insufficient for M4.** | Specify whether retry is permitted only with a fresh attempt/decision and how provider idempotency is handled. |
| Final egress policy covering endpoint, region, retention/no-training, payload redaction and destination change | Existing provider classification is local/external by provider name; route has provider/model but no endpoint/region/retention/payload-hash policy binding. | **Absent / incompatible until designed.** | Extend authoritative policy input/output or provide a versioned M2.5 egress API that exposes these constraints. |
| Human approval linked to durable authority | Gateway receives boolean `approval_granted`; other runtime approval controls exist separately, but no M4-ready approval/attempt binding is exposed here. | **Unverified for M4.** | M2.5 owner maps durable approval identity/status/expiry to egress attempt authorization without trusting a caller boolean. |
| Minimal audit for decision/attempt/recovery | Current audit sink records provider/model/token/cost/fallback or denial reason; no decision/attempt IDs, hashes, outcome/recovery references exist. | **Absent / incompatible until designed.** | Define minimal, PHI-free decision/attempt/recovery audit fields and retention/access ownership. |

## 5. Required versioned M2.5 interface assessment

Before M4-GOV-03 can be approved, the M2.5 owner and independent safety
reviewer must provide a versioned interface assessment that answers:

1. Which authoritative M2.5 component owns attempt persistence, state
   transitions, sender identity, expiration, recovery lease, and audit?
2. What conditional operation proves an attempt is bound to exactly one
   immutable payload/destination/operation/policy tuple?
3. How are `RESERVED`, `CONSUMED`, `UNCERTAIN`, confirmed provider outcomes,
   expiry, and cancellation represented without claiming exactly-once provider
   delivery?
4. How does a retry obtain a new decision while preserving an approved provider
   idempotency strategy, if supported?
5. How does existing provider fallback become safe for an M4 egress attempt,
   especially when provider/model/region/retention changes would invalidate the
   decision binding?
6. How is high-impact approval resolved from durable authority rather than a
   caller-controlled boolean for the M4 path?
7. Which audit fields are recorded without retaining raw PHI/PII or payload?

The result must be an approved M4-GOV-03 record with named owner/approver IDs,
scope, dates, immutable decision reference, evidence hashes, and independent
verification. A draft interface or this analysis is not an approval.

## 6. Required future synthetic tests

No tests were run for this analysis. A future separately authorized M2.5 change
would need synthetic tests for concurrent reservation/consumption, changed
payload/destination rejection, expiry, provider fallback denial, crash after
`CONSUMED`, unknown provider result, fresh-decision retry, provider idempotency
where available, high-impact approval binding, and PHI-free audit output.

## 7. Decision and hold

The current source establishes an existing M2.5 safety boundary but does not
establish compatibility with the M4.1 Revision 4 atomic egress-attempt
contract. M4-GOV-03 remains `PENDING` / `DRAFT`; M4.2/M4.3 remain blocked.
M2.5 remains the sole safety/egress authority, governance approvals remain
`0/7`, and the six M3.2.1 live gates remain pending. No database connection,
migration, provider call, external egress, worker activation, or infrastructure
operation was performed.
