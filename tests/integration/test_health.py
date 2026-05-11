"""End-to-end health endpoint tests.

These hit the real Postgres / Redis / Milvus through the app's lifespan,
exercising the dependency-injection wiring as well as the FastAPI router.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_liveness_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_all_subsystems_healthy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert set(body["checks"].keys()) == {"database", "redis", "milvus"}
    for name, check in body["checks"].items():
        assert check["status"] == "ok", f"{name} reported {check}"


async def test_readiness_returns_503_when_redis_check_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readiness must surface partial outages with a 503, not a 200."""
    from src.api.endpoints import health

    async def _broken_redis(_redis: object) -> dict[str, str]:
        return {"status": "error", "detail": "simulated outage"}

    monkeypatch.setattr(health, "_check_redis", _broken_redis)
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"]["status"] == "error"
    # Other subsystems should still report whatever their actual status is —
    # at least the schema must remain stable.
    assert "database" in body["checks"]
    assert "milvus" in body["checks"]
