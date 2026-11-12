# Run from the repository root in PowerShell.
Write-Host "=== Compose containers ==="
docker compose ps -a

Write-Host "`n=== API logs ==="
docker compose logs --no-color --tail=150 api

Write-Host "`n=== API port mapping ==="
docker compose port api 8000

Write-Host "`n=== Local TCP port 8000 ==="
Test-NetConnection 127.0.0.1 -Port 8000

Write-Host "`n=== API endpoint ==="
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/health" -UseBasicParsing -TimeoutSec 8 |
        Select-Object StatusCode, Content
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
}
