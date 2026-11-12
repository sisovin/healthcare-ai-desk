$ErrorActionPreference = "Stop"

function Get-ComposeHostPort([string]$service, [string]$containerPort, [string]$fallback) {
    $binding = docker compose port $service $containerPort 2>$null
    if ($LASTEXITCODE -eq 0 -and $binding) {
        return ($binding.Trim() -split ":")[-1]
    }
    return $fallback
}

function Show-ComposeDiagnostics {
    Write-Host "`n--- docker compose ps -a ---" -ForegroundColor Cyan
    docker compose ps -a
    Write-Host "`n--- API logs (last 100 lines) ---" -ForegroundColor Cyan
    docker compose logs --no-color --tail=100 api
    Write-Host "`n--- API port mapping ---" -ForegroundColor Cyan
    docker compose port api 8000
}

$apiPort = Get-ComposeHostPort -service "api" -containerPort "8000" -fallback "8000"
$webPort = Get-ComposeHostPort -service "web" -containerPort "5173" -fallback "5173"

Write-Host "[1/4] Container status"
docker compose ps -a
if ($LASTEXITCODE -ne 0) {
    throw "docker compose ps failed. Confirm Docker Desktop is running and this folder contains docker-compose.yml."
}

Write-Host "`n[2/4] API liveness: http://127.0.0.1:$apiPort/api/v1/health"
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$apiPort/api/v1/health" -TimeoutSec 10
    $health | ConvertTo-Json -Depth 5
} catch {
    Write-Host "Underlying request error: $($_.Exception.Message)" -ForegroundColor Red
    Show-ComposeDiagnostics
    throw "API liveness failed. Use the container state and API logs above to identify the root cause."
}

Write-Host "`n[3/4] API readiness (MySQL + Redis)"
try {
    $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$apiPort/api/v1/ready" -TimeoutSec 10
    $ready | ConvertTo-Json -Depth 5
} catch {
    Write-Host "Underlying request error: $($_.Exception.Message)" -ForegroundColor Red
    try {
        $readyError = Invoke-WebRequest -Uri "http://127.0.0.1:$apiPort/api/v1/ready" -SkipHttpErrorCheck -UseBasicParsing -TimeoutSec 10
        if ($readyError.Content) {
            Write-Host "Readiness response: $($readyError.Content)" -ForegroundColor Yellow
        }
    } catch {
        # Best-effort diagnostics only.
    }
    Write-Host "`n--- MySQL logs (last 80 lines) ---" -ForegroundColor Cyan
    docker compose logs --no-color --tail=80 mysql
    Write-Host "`n--- Redis logs (last 80 lines) ---" -ForegroundColor Cyan
    docker compose logs --no-color --tail=80 redis
    throw "API readiness failed. Inspect the dependency checks and logs above."
}

Write-Host "`n[4/4] Frontend HTTP response: http://127.0.0.1:$webPort"
try {
    $web = Invoke-WebRequest -Uri "http://127.0.0.1:$webPort" -UseBasicParsing -TimeoutSec 10
    Write-Host "Frontend HTTP status: $($web.StatusCode)"
} catch {
    Write-Host "Underlying request error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "`n--- Web logs (last 100 lines) ---" -ForegroundColor Cyan
    docker compose logs --no-color --tail=100 web
    throw "Frontend check failed. Inspect the web logs above."
}

Write-Host "`nAll M1.1 smoke checks completed. This is not a substitute for automated unit/integration tests." -ForegroundColor Green
