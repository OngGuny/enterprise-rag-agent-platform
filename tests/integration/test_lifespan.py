"""Verify that lifespan boots and tears down external service managers.

The app's startup must connect Redis and Milvus (best-effort for Milvus),
and shutdown must cleanly release those resources. The fail-fast guards
(`get_client()` raising RuntimeError when not connected) are also covered.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from src.core.milvus import MilvusManager
from src.core.redis import RedisManager

pytestmark = pytest.mark.integration


async def test_redis_manager_is_live_inside_lifespan(app_with_lifespan: FastAPI) -> None:
    client = RedisManager.get_client()
    try:
        assert await client.ping() is True
    finally:
        await client.aclose()


async def test_milvus_manager_is_live_inside_lifespan(app_with_lifespan: FastAPI) -> None:
    client = MilvusManager.get_client()
    # list_collections is a sync RPC; success implies the channel is up.
    result = client.list_collections()
    assert isinstance(result, list)


async def test_managers_raise_after_disconnect() -> None:
    """After the lifespan exits (which the prior tests' fixtures already did),
    invoking get_client() without an active connection must fail loudly.

    This guards the contract documented in ADR-003 — lifespan-or-bust.
    """
    # Force a clean teardown to be independent of test ordering.
    await RedisManager.disconnect()
    MilvusManager.disconnect()

    with pytest.raises(RuntimeError, match="Redis not connected"):
        RedisManager.get_client()

    with pytest.raises(RuntimeError, match="Milvus not connected"):
        MilvusManager.get_client()
