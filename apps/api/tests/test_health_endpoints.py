from fastapi.testclient import TestClient

from app.main import app
from app.api.v1 import health as health_module


client = TestClient(app)


class _DummyRedisClient:
    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None


def test_liveness_returns_ok() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_returns_expected_links() -> None:
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["docs"] == "/docs"
    assert payload["health"] == "/api/v1/health"


def test_readiness_returns_ready_when_dependencies_ok(monkeypatch) -> None:
    monkeypatch.setattr(health_module, "check_database_connection", lambda: None)
    monkeypatch.setattr(health_module, "get_redis_client", lambda: _DummyRedisClient())

    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"mysql": "ok", "redis": "ok"}}


def test_readiness_returns_503_when_mysql_fails(monkeypatch) -> None:
    def _mysql_error() -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(health_module, "check_database_connection", _mysql_error)
    monkeypatch.setattr(health_module, "get_redis_client", lambda: _DummyRedisClient())

    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    payload = response.json()["detail"]
    assert payload["status"] == "not_ready"
    assert payload["checks"]["mysql"] == "error: RuntimeError"
    assert payload["checks"]["redis"] == "ok"


def test_readiness_returns_503_when_redis_fails(monkeypatch) -> None:
    class _FailingRedisClient(_DummyRedisClient):
        def ping(self) -> bool:
            raise RuntimeError("redis down")

    monkeypatch.setattr(health_module, "check_database_connection", lambda: None)
    monkeypatch.setattr(health_module, "get_redis_client", lambda: _FailingRedisClient())

    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    payload = response.json()["detail"]
    assert payload["status"] == "not_ready"
    assert payload["checks"]["mysql"] == "ok"
    assert payload["checks"]["redis"] == "error: RuntimeError"
