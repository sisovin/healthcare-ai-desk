from fastapi import APIRouter, HTTPException
from redis.exceptions import RedisError

from app.core.dependencies import get_redis_client
from app.db.session import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict:
    """Process liveness only; independent of infrastructure dependencies."""
    return {"status": "ok", "service": "healthcare-ai-desk-api"}


@router.get("/ready")
def readiness() -> dict:
    """Readiness check for required infrastructure dependencies."""
    checks = {"mysql": "unknown", "redis": "unknown"}

    try:
        check_database_connection()
        checks["mysql"] = "ok"
    except Exception as exc:
        checks["mysql"] = f"error: {type(exc).__name__}"

    client = get_redis_client()
    try:
        client.ping()
        checks["redis"] = "ok"
    except (RedisError, Exception) as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    finally:
        client.close()

    if any(value != "ok" for value in checks.values()):
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})

    return {"status": "ready", "checks": checks}
