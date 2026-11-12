Current automated coverage:
- API liveness endpoint
- API readiness endpoint (dependency healthy / dependency failure paths)
- Root metadata endpoint

Run from repository root (safe: does not delete MySQL/Redis volumes):
```powershell
docker compose up -d --build api
docker compose exec -T api python -m pytest -q tests
```

Smoke checks are still recommended:
```powershell
.\scripts\verify.ps1
```
