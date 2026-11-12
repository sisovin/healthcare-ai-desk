Current automated coverage:
- API liveness endpoint
- API readiness endpoint (dependency healthy / dependency failure paths)
- Root metadata endpoint
- Database URL parsing with special characters
- SQLAlchemy metadata/schema creation
- Database connectivity probe function
- Core business schema metadata (organizations, users, projects, memberships, patient records)
- Organization isolation checks (required header, org existence, same-org scope enforcement)
- Authentication security helpers (Argon2id hash/verify, JWT access token, refresh token hashing)
- RBAC permission mapping checks (role-to-permission enforcement baseline)

Run from repository root (safe: does not delete MySQL/Redis volumes):
```powershell
docker compose up -d --build api
docker compose exec -T api python -m pytest -q tests
```

Run verbose test report:
```powershell
docker compose exec -T api python -m pytest -v tests
```

Smoke checks are still recommended:
```powershell
.\scripts\verify.ps1
```
