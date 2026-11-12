# M2 — Agent Management & Registry

## Objective
Deliver secure, organization-scoped Agent Management and Registry capabilities on top of M1.3 security controls and M1.4 database foundation.

## Security baseline inheritance (mandatory)
- Organization isolation (`X-Organization-Id`) remains required.
- Access token org scope must match request org scope.
- RBAC permission guards remain centralized.
- Refresh token revocation policy remains unchanged.

## M2 scope
1. Agent Registry API and service layer.
2. Agent lifecycle management (draft/active/disabled/archived).
3. Agent-to-project assignment APIs with organization-safe constraints.
4. Auditability for agent configuration changes and assignments.
5. Validation/test baseline for agent security boundaries.

## Milestone breakdown
- M2.1: Registry domain contracts and CRUD foundations.
- M2.2: Organization-scoped API + RBAC guard wiring.
- M2.3: Agent runtime engine (published versions, lifecycle, task queue, audit logs, human approval).
- M2.4: Runtime reliability and observability hardening.

## Out of scope for M2
- Multi-agent runtime orchestration/group chat execution engine.
- Human approval workflow runtime.
- Shared memory and RAG orchestration.
- Production-grade distributed scheduling.

## Core acceptance criteria
- All agent resources are organization-scoped end-to-end.
- No cross-organization read/write/assignment path is possible.
- All write paths require explicit RBAC permission checks.
- API and integration tests validate both success and denial paths.

## Recommended next roadmap
1. M2.5 — LLM Provider Gateway & Agent Tool Execution
2. M3.0 — Supervisor Agent & Multi-Agent Group Chat
