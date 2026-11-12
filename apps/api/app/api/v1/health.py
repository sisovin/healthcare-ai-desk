from fastapi import APIRouter, HTTPException
import pymysql
from redis.exceptions import RedisError

from app.core.dependencies import get_mysql_connection, get_redis_client

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
        with get_mysql_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
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
