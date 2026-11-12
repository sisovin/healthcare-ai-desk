# Healthcare AI Desk — M1.3 Security Foundation

Local-first starter repository for Windows 10 + Docker Desktop + VS Code.

## Included (current baseline)
- FastAPI backend with `/api/v1/health` and `/api/v1/ready`
- React + Vite + Tailwind CSS v4 starter UI
- MySQL 8.4 and Redis 7 (localhost-bound host ports)
- Docker Compose development environment
- PowerShell verification scripts (`verify.ps1`, `diagnose-api.ps1`)
- SQLAlchemy + Alembic migration chain through `20261112_0006`
- Organization isolation guardrails (`X-Organization-Id`)
- Authentication foundation: Email/Password (Argon2id) + JWT access + refresh token rotation/revocation
- RBAC foundation: `owner`, `admin`, `manager`, `member`, `viewer`
- Agent Management database foundation linked to organization scope

## Prerequisites
1. Windows 10 64-bit.
2. Docker Desktop installed and running, preferably using the WSL 2 backend.
3. VS Code and Git (recommended).
4. At least 8 GB RAM. Close memory-intensive applications before starting Docker.

## Quick start (PowerShell)

```powershell
Copy-Item .env.example .env
# Edit .env and replace the development secrets/passwords.
docker compose config
docker compose up -d --build
docker compose ps
```

Open:
- Frontend: http://localhost:5173
- API health: http://localhost:8000/api/v1/health
- API readiness: http://localhost:8000/api/v1/ready
- Swagger UI: http://localhost:8000/docs

## Verify

```powershell
.\scripts\verify.ps1
```

The script checks container status and HTTP responses. It is a smoke check, not a complete automated test suite.

## Automated tests (volume-safe)

The following sequence preserves existing MySQL/Redis volumes (no data deletion):

```powershell
# 1) Confirm current stack status
docker compose ps

# 2) Rebuild API image and keep services running
docker compose up -d --build api

# 3) Run API automated tests
docker compose exec -T api python -m pytest -q tests

# 4) Run end-to-end smoke verification
.\scripts\verify.ps1
```

Do not run `docker compose down -v` unless you intentionally want to remove database/cache data.

## M1.2 database foundation

API now includes:
- SQLAlchemy engine/session lifecycle
- Initial declarative model (`system_settings`)
- Alembic migration scaffold and versioned migrations (`20261112_0001`, `20261112_0002`, `20261112_0003`, `20261112_0004`, `20261112_0005`)
- Core business schema tables (`organizations`, `users`, `projects`, `organization_memberships`, `patient_records`)
- Organization isolation guardrails (`X-Organization-Id` context validation + cross-org access denial)
- Extended automated tests for schema and DB helpers

Run migration:
```powershell
docker compose exec -T api alembic upgrade head
```

## M1.3 authentication decision

Healthcare AI Desk uses:
- Email + Password
- Argon2id password hashing
- JWT access tokens
- Refresh tokens with rotation/revocation stored as token hashes in database
- Organization-scoped token policy (refresh tokens tied to organization and revoked by scope)
- RBAC permission guard foundation (`owner`, `admin`, `manager`, `member`, `viewer`)

## Agent Management database foundation

Agent Management schema now includes:
- `agent_profiles` (organization-scoped agent registry)
- `agent_project_assignments` (organization-scoped assignment of agents to projects)
- Composite organization constraints to enforce same-organization agent/project linkage
- RBAC permissions for agent operations (`agent.read`, `agent.write`, `agent.assign`)

M2.1 now adds:
- Agent Registry CRUD endpoints:
  - `POST /api/v1/agents`
  - `GET /api/v1/agents`
  - `GET /api/v1/agents/{agent_id}`
  - `PATCH /api/v1/agents/{agent_id}`
- Organization-scoped query/mutation guards on all `/agents` operations
- Endpoint tests for CRUD + org/RBAC denial paths

## Documentation map
- `docs/M0.0_MASTER_PROJECT.md`
- `docs/M0.1_ADDITIONAL_PROJECT_DOCS.md`
- `docs/M1.1_IMPLEMENTATION_NOTES.md`
- `docs/M1.1_API_LIVENESS_TROUBLESHOOTING.md`
- `docs/M1.2.1_DATABASE_FOUNDATION.md`
- `docs/M1.2.2_CORE_BUSINESS_SCHEMA.md`
- `docs/M1.2.3_SCHEMA_HARDENING.md`
- `docs/M1.3_AUTH_RBAC_ARCHITECTURE.md`
- `docs/M1.4_AGENT_MANAGEMENT_DATABASE_FOUNDATION.md`
- `docs/M2_AGENT_MANAGEMENT_REGISTRY.md`
- `docs/M2.1_AGENT_REGISTRY_FOUNDATION.md`
- `docs/M2.2_AGENT_REGISTRY_SECURITY_INTEGRATION.md`
- `docs/M2.3_AGENT_PROJECT_ASSIGNMENT_WORKFLOWS.md`
- `docs/M2.4_AGENT_REGISTRY_AUDIT_AND_ACCEPTANCE.md`

## Useful commands

```powershell
docker compose ps
docker compose logs -f api
docker compose logs -f web
docker compose logs -f mysql
docker compose logs -f redis
docker compose down
# DESTRUCTIVE: deletes the local database and Redis volumes
docker compose down -v
docker compose up -d --build
```

## Troubleshooting
- If Docker is unavailable, start Docker Desktop and wait for the engine.
- If a port is occupied, change `WEB_PORT`, `API_PORT`, `MYSQL_PORT`, or `REDIS_PORT` in `.env`.
- MySQL's first startup can take time; inspect `docker compose logs -f mysql`.
- Browser API requests use `/api` through the Vite proxy. Do not use `http://api:8000` in browser code.
- For slow Windows bind mounts, keep the repository inside the WSL2 Linux filesystem.

## Current boundaries (post-M2.1)
This baseline still does not yet provide:
- Agent-to-project assignment APIs (M2.3) and audit workflows (M2.4)
- Multi-agent group chat orchestration
- Human approval workflow engine
- Shared organizational memory and healthcare RAG stack
- Full clinical workflow modules (MNCH workflow automation, reporting pipelines)
- Production deployment hardening and SRE controls

Do not enter real patient-identifiable or confidential healthcare data into this starter.
