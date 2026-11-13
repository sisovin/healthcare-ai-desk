# Healthcare AI Desk — M4: Shared Memory & Healthcare RAG

**Status:** Architecture and implementation planning only.
**Execution authorization:** Not granted by this document.
**Dependencies:** M1–M2.5 remain authoritative; M3 work remains subject to its
separate acceptance gates.
**Safety boundary:** M2.5 is the sole authority for high-impact approval and
external-LLM egress policy.

**M4.1 Revision 3:** Detailed retrieval authorization, revocation fencing,
atomic egress-attempt semantics, protected preprocessing, exact index
generation activation, governance requirements, and source provenance are
defined in
[`M4.1_SECURITY_AND_ARCHITECTURE_CONTRACT_REVISION_3.md`](M4.1_SECURITY_AND_ARCHITECTURE_CONTRACT_REVISION_3.md).

## 1. Purpose

M4 introduces durable, tenant-safe organizational memory and a healthcare
knowledge-retrieval capability. It enables authorized agents and users to find
approved clinical-operational knowledge, SOPs, policies, and project-scoped
reference material without turning retrieved text into execution authority.

M4 does **not**:

- replace M2.5 safety policy or human approval;
- authorize diagnosis, treatment, prescribing, or other high-impact action;
- make a retrieved document a source of truth for patient-specific decisions;
- permit patient-identifying data to be sent to an external embedding or LLM
  provider without the required data protection, policy decision, and consent;
- authorize a database migration, Qdrant deployment, background worker, or
  external provider connection.

## 2. Architectural decisions

| Concern | Decision |
| --- | --- |
| Authoritative metadata | MySQL stores documents, versions, ACLs, lifecycle, retention, audit references, and ingestion jobs. |
| Retrieval index | Qdrant is a rebuildable, tenant-filtered retrieval index; it is not authoritative state. |
| Delivery | Transactional Outbox remains the durable source for post-commit indexing work; Redis is a recoverable delivery accelerator only. |
| Source immutability | Every ingested document version is content-addressed with SHA-256; chunks retain source/version/page-or-section provenance. |
| Tenant boundaries | Every MySQL query, Qdrant query, cache key, job, chunk, and audit event is organization-scoped; project scope is additive. |
| Agent access | The caller identity and M1/M2 assignment/RBAC controls determine retrieval eligibility; client-supplied tenant or agent identity is never trusted. |
| Safety | Retrieval may provide context only. Tool execution and high-impact actions still traverse M2.5 policy and approval gates. |

## 3. Memory domains and data classification

M4 separates memory by purpose and sensitivity:

| Domain | Examples | Storage and access rule |
| --- | --- | --- |
| Organizational knowledge | Approved SOPs, policies, care pathways, product instructions | Versioned and tenant/project scoped; retrieval requires RBAC/ACL check. |
| Conversation-derived memory | Explicitly curated non-patient preferences, project decisions, summaries | Opt-in, provenance-linked, minimal content; not a raw conversation mirror. |
| Clinical reference corpus | Approved guidelines and licensed reference content | Source/license/version provenance required; retrieval returns citations. |
| Patient-identifying or regulated clinical data | Names, IDs, notes, images, records | Excluded from generic shared memory and external embedding by default. A future local-only protected workflow requires a separate approved design. |

Classification is server-owned. A document or chunk may be `public_within_org`,
`project_restricted`, `clinical_reference`, `confidential`, or
`patient_restricted`; only the first three are in initial M4 retrieval scope.
`patient_restricted` is deny-by-default until a later, separately approved
capability exists.

## 4. Retrieval and egress flow

```text
Authorized caller
  → RBAC + organization/project scope
  → memory policy and PII classification
  → approved retrieval filters in Qdrant
  → provenance-bearing chunks + citations
  → M2.5 egress decision/redaction (if an LLM is requested)
  → answer or agent context
  → audit event
```

The service must reject a query if its authoritative organization, project,
user, agent assignment, or clearance cannot be established. It must return no
cross-tenant fallback results.

For an external provider, the system must first apply M2.5 policy, allowed
provider/model routing, data-minimization, PII detection/redaction, and any
required user/organization authorization. If those checks fail, it must deny
egress rather than use a less-safe provider fallback.

## 5. Proposed data model (design only)

The final DDL must be additive, forward-only, and based on a verified Alembic
head. Names below are implementation targets, not authorization to migrate.

| Entity | Core invariant |
| --- | --- |
| `knowledge_documents` | Composite tenant identity; immutable source metadata and current lifecycle only. |
| `knowledge_document_versions` | `(organization_id, document_id, version_number)` is unique; `content_sha256` is immutable after ingestion. |
| `knowledge_chunks` | Each chunk references one document version and carries ordinal, text classification, redacted-content hash, and source locator. |
| `knowledge_acl_entries` | Grants are explicit and organization-scoped; no global wildcard grant. |
| `knowledge_ingestion_jobs` | Idempotency key, status, attempt count, lease/retry metadata, error code, and no raw sensitive error payload. |
| `memory_entries` | Explicitly curated memory with provenance, expiry/retention policy, visibility, and revocation state. |
| `memory_audit_logs` | Minimal audit metadata: actor, purpose, scope, action, document/version/chunk identifiers, policy result, correlation ID. No raw retrieved text or patient identifiers. |

All relations that cross tenant-scoped entities must use matching composite
foreign keys and referenced unique keys. Document deletion is logical first:
revocation immediately blocks retrieval; physical deletion/index purge follows
retention and legal-hold rules through an auditable workflow.

## 6. Ingestion, indexing, and recovery contract

1. Validate uploader authorization, organization/project scope, source type,
   license/provenance, classification, size, and malware/content-processing
   policy.
2. Create document/version/chunk metadata, audit record, and an outbox event in
   one MySQL transaction.
3. After commit, a durable dispatcher delivers the indexing event at least once.
4. The indexer validates the authoritative version and ACL state again, writes
   Qdrant vectors with mandatory organization/project payload filters, then
   records an idempotent indexing receipt.
5. Retry and replay may produce duplicate delivery but must not create duplicate
   chunks, vectors, or audit side effects. Revoked/expired versions are removed
   from retrieval before or together with index purge.

Embedding inputs follow the same egress policy as LLM inputs. Initial M4 must
prefer a provider and deployment model that meet the document classification
policy. If no permitted embedding route is available, ingestion remains
pending/denied and the source is not indexed through an unapproved fallback.

## 7. Retrieval contract

Retrieval requests contain a server-derived actor, organization, optional
project, approved purpose, query, filters, and correlation ID. The server:

- validates the purpose and access controls before vector search;
- applies organization and project filters as mandatory predicates, not
  post-filtering;
- uses only active, approved, non-revoked document versions;
- enforces a bounded result count and context byte/token budget;
- returns source/version/chunk citations and a disclosure that retrieved text
  is reference context, not an autonomous clinical decision;
- records minimal audit metadata and decision reasons;
- refuses retrieval when policy or scope is ambiguous.

Scores are ranking signals, not trust or safety scores. Confidence language in
agent responses must not overstate source quality; M4 must preserve citation
and version context so consumers can review the source.

## 8. Security, privacy, and retention controls

- Encrypt protected document payloads and secrets at rest with managed key
  references; no plaintext fallback on encryption failure.
- Enforce least privilege for original payload, chunk text, metadata, vector
  payloads, and audit views independently.
- Detect and classify PII/PHI before chunking, embedding, logging, or egress.
  Raw content is excluded from outbox, Redis, and generic audit metadata.
- Keep only the minimum query/retrieval audit metadata necessary for security,
  compliance, and incident response. Hash/redact user query content where raw
  retention is unnecessary.
- Apply retention, revocation, legal-hold, and cryptographic-key rotation rules
  to both authoritative content and rebuildable indexes. Index deletion alone
  is not proof of authoritative deletion.
- Treat retrieved instructions as untrusted content: they cannot override
  system policy, M2.5, RBAC, or tool permissions.

## 9. Delivery sequence

| Package | Scope | Completion evidence |
| --- | --- | --- |
| M4.1 | Architecture, classification, ACL, retention, and egress contract | Independent review of the approved design and migration prerequisites. |
| M4.2 | Forward-only metadata/memory schema and scoped repository layer | Disposable migration rehearsal, composite-FK/tenant-isolation tests, no shared-volume reset. |
| M4.3 | Ingestion and idempotent Qdrant indexing pipeline | Atomic outbox tests, retry/replay, revocation, and index-rebuild evidence. |
| M4.4 | Retrieval API and agent context integration | Cross-tenant/RBAC/ACL tests, citation and budget tests, PII-egress denial tests. |
| M4.5 | Healthcare RAG safety and operational acceptance | Red-team prompt-injection tests, audit/retention checks, recovery, full regression, and independent review. |

M4.3 and later must not start until M4.2 establishes the authoritative schema
and a tested isolation contract. M4 does not unblock any separately gated M3
work.

## 10. Initial acceptance gate for M4.1

Before M4 implementation begins, reviewers must confirm:

- the actual MySQL/Alembic head and existing M1–M3 contracts;
- the exact Qdrant deployment boundary, authentication, collection strategy,
  backup/rebuild procedure, and no-cross-tenant filter enforcement;
- approved document classifications, embedding routes, and external egress
  controls;
- source licensing/provenance policy and clinical-content review ownership;
- retention, legal-hold, deletion, encryption-key, and audit requirements;
- test fixtures containing no real patient data;
- that M2.5 retains all high-impact approval authority.

## 11. Current milestone decision

M4 is **proposed for review-only planning**. It is not an authorization to
create infrastructure, modify existing MySQL/Redis volumes, run migrations,
enable Qdrant, ingest healthcare documents, or send data to any embedding/LLM
provider.
