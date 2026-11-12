# Healthcare AI Desk — M1.1

Local-first starter repository for Windows 10 + Docker Desktop + VS Code.

## Included
- FastAPI backend with `/api/v1/health` and `/api/v1/ready`
- React + Vite + Tailwind CSS v4 starter UI
- MySQL 8.4 and Redis 7
- Docker Compose development environment
- PowerShell setup and verification scripts
- VS Code workspace recommendations

> M1.1 is infrastructure scaffolding only. Authentication, organization/project modules,
> database migrations, agent orchestration, and clinical workflows are not implemented yet.
> No tests are claimed to have passed. Run the verification steps below on your computer.

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

## M1.1 boundaries
This milestone does not yet provide user accounts/JWT, Alembic migrations, organization/project CRUD,
agent registry/group chat, patient record storage, or clinical decision support.

Do not enter real patient-identifiable or confidential healthcare data into this starter.
