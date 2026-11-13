# Healthcare AI Desk — M4 Shared Memory & Healthcare RAG
## Independent Architecture & Security Review (Review-Only)

**Review date:** 2026-11-13
**Source:** User-supplied `M4_SHARED_MEMORY_AND_HEALTHCARE_RAG.md` (188 document lines).
**Disposition:** **Conditionally accepted as an architecture planning baseline; M4.1 design hardening is required before M4.2 implementation planning is signed off.**
**Execution authorization:** **FALSE.** No MySQL, Redis, Qdrant, Docker, Alembic, migration, ingestion, embedding, external LLM, writer or worker operation was authorized or performed.

### 1. Confirmed architecture strengths

1. **MySQL authoritative; Qdrant rebuildable:** MySQL owns document/version/ACL/retention/audit metadata. Qdrant is a scoped, rebuildable retrieval index, not a source of authorization or execution authority (source §2, lines 27–37).
2. **M2.5 boundary retained:** Retrieved text cannot confer clinical decision, provider egress, tool execution, or human-approval authority (source §1, §4, §8).
3. **Default exclusion of patient-restricted memory:** Patient-identifying data are excluded from generic shared memory and external embedding absent a separate approved workflow (source §3, lines 39–54).
4. **Durable ingestion intent:** MySQL transaction and transactional outbox precede at-least-once indexing; idempotent receipts and revocation are specified as principles (source §6, lines 98–116).
5. **Forward-only planning and gated delivery:** M4.1–M4.5 and separate M3 review gates remain intact (source §9–11).

### 2. Blocking M4.1 design decisions (not claims of implemented vulnerabilities)

| ID | Priority | Decision needed | Acceptance rule |
|---|---|---|---|
| M4-D01 | P0 before retrieval implementation | **Authoritative per-hit read-time reauthorization** after Qdrant returns candidates | Recheck caller identity, tenant/project ACL, current assignment/clearance, document-version approval, classification, expiry, and revocation in MySQL **immediately before any chunk/body/citation is disclosed**. A stale Qdrant payload or cached hit cannot override MySQL. |
| M4-D02 | P0 before indexing/revocation implementation | **Revocation/reindex race fencing** | Index jobs bind to an immutable document version and index generation; revoke increments an authoritative generation/tombstone and blocks reads immediately. Old workers cannot resurrect revoked/expired vectors; purge is eventually verified and audited. |
| M4-D03 | P0 before external embedding | **Query and document embedding egress contract** | Both *user queries* and *document chunks*, including reranker requests, undergo pre-provider M2.5 checks with class-specific allowlists, redaction/data minimization, provider destination, model, retention terms, and fail-closed denial. No automatic less-safe fallback. |
| M4-D04 | P0 before schema/ingestion implementation | **Immutable source and rebuild provenance** | Specify authorized encrypted source-object storage and content-hash verification, chunk-extractor/redaction pipeline version, embedding model/version, Qdrant collection/index schema generation, and deterministic point identity. An index can be rebuilt solely from approved authoritative source versions without duplicate or leaked records. |

### 3. Additional requirements to incorporate in M4.1

**Tenant-scoping contract (P1):** Define organization-wide visibility versus project-restricted visibility as an explicit allowed-set predicate. Server-owned filters must be compulsory at search time; MySQL post-hit checks remain mandatory. Forbid user-specified ACL/tenant overrides. Qdrant collection strategy, credentials, network boundary, backups and plaintext payload exposure are still open design choices, correctly identified in the source gate.

**Clinical freshness and governance (P1):** For clinical SOP/guideline versions, store issuer, geographic jurisdiction, clinical reviewer, approval/effective/expiry/review dates, superseded status, source license and citation URL/section. Retrieval must fail closed for revoked/superseded or unapproved clinical guidance, and returned citations must identify the specific approved edition. Do not infer clinical correctness from vector similarity.

**Memory poisoning and prompt-injection controls (P1):** Require explicit opt-in for conversation-derived memory, source-linked provenance, bounded TTL, revocation, and review or authorization for promotion into shared memory. Retrieved text is data, not policy or instructions. Test embedded directives requesting role escalation, credential disclosure, external provider use, or tool invocation.

**Security operations and deletion (P1):** Specify encryption key ownership and rotation, audit field allowlist, access to original blobs versus Qdrant payloads, legal hold, retention and backup/deletion semantics, and proof that a purge request cannot override a legal hold. Set defined PII/PHI detection failure behavior rather than silently accepting false negatives. Process uploaded files in a sandbox with size/type/resource limits and malware controls.

### 4. Suggested canonical M4 retrieval flow

```text
Authenticated user/agent
  -> server-resolved tenant/project/purpose/assignment/clearance
  -> M2.5 query-classification and embedding egress authorization (if needed)
  -> embed locally or via separately allowed provider; otherwise deny
  -> Qdrant compulsory tenant/visibility filters (candidates only)
  -> MySQL authoritative per-hit ACL/version/revocation/effective-date recheck
  -> bounded, verified text chunks and provenance citations
  -> M2.5 final document/context egress check for any provider request
  -> answer/context with non-clinical-autonomy boundary
  -> minimal, PHI-free audit event
```

Cache reads must enforce equivalent per-hit revocation/ACL checks; keys and invalidation use tenant, principal/purpose, document version, and authorization generation where relevant.

### 5. Review-only acceptance matrix (no infrastructure execution)

| Test ID | Offline/design acceptance requirement |
|---|---|
| M4-T01 | A forged cross-tenant or project filter is refused by request builder and per-hit authorization. |
| M4-T02 | Qdrant returns a candidate with a revoked MySQL document version: **zero chunk text disclosed**. |
| M4-T03 | ACL revoked between vector lookup and response assembly: **zero text disclosed**. |
| M4-T04 | Revoke occurs after an indexing job was leased: an old job **cannot re-create searchable vectors**. |
| M4-T05 | Duplicate outbox delivery/rebuild is idempotent for point IDs and receipts. |
| M4-T06 | Restricted query or chunk denied for external embeddings; no less-safe fallback. |
| M4-T07 | A retrieved document with prompt-injection directives cannot grant any approval/tool/provider permission. |
| M4-T08 | Superseded/expired/unapproved healthcare reference is not treated as an active citation. |
| M4-T09 | Source content hash, extracted chunk hash, model version, redaction version, and citation locator agree. |
| M4-T10 | Deletion, legal hold, retention and audit metadata preserve correct authoritative/in-index states. |

This matrix defines **future tests**, not tests executed during this review.

### 6. Final independent review decision

- **M4 architecture planning:** **Conditionally accepted.**
- **M4.1 sign-off:** Pending explicit decisions D01–D04, external owner/policy mapping and updated acceptance matrix.
- **M4.2 migration/schema work:** Not authorized, and actual Alembic head not verified here.
- **M4.3 Qdrant ingestion/indexing:** Not authorized.
- **M4.4 retrieval/agent integration:** Not authorized.
- **M4.5 production/healthcare acceptance:** Not certified.
- **M3.2.1 six live gates:** Remain independently pending; this M4 review cannot unblock them.
- **M2.5:** Retains all approval and PII/PHI egress authority.

**Reminder:** SHA-256 content checks provide change detection, not authorization or a cryptographic identity proof by themselves. Reference text and RAG scores cannot independently authorize patient-specific clinical decisions.
