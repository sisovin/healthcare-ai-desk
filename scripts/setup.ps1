$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI not found. Install Docker Desktop first."
}
docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker engine is not running. Start Docker Desktop and retry."
}
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env. Edit its passwords and secrets before starting." -ForegroundColor Yellow
} else {
    Write-Host ".env already exists; leaving it unchanged."
}
docker compose config
if ($LASTEXITCODE -ne 0) { throw "Docker Compose configuration validation failed." }
Write-Host "Preflight complete. Run: docker compose up -d --build" -ForegroundColor Green
