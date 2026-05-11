"""Shared fixtures for the test suite.

These integration tests boot the real FastAPI lifespan and connect to
Postgres / Redis / Milvus running on localhost. Bring the dependencies
up first:

    docker compose up -d postgres redis milvus

The environment overrides below are applied **before** any ``src.*``
import so that ``Settings`` (cached via ``lru_cache``) is built against
the localhost endpoints — independent of the developer's `.env`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

# --- Test environment overrides (must happen before importing src.*) -------
_TEST_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/ragplatform",
    "REDIS_URL": "redis://localhost:6379/15",
    "REDIS_MAX_CONNECTIONS": "10",
    "MILVUS_URI": "http://localhost:19530",
    "MILVUS_DEFAULT_COLLECTION": "test_documents",
    "OPENAI_API_KEY": "test-not-used",
    "DEBUG": "true",
    "LOG_LEVEL": "WARNING",
    "CORS_ORIGINS": '["*"]',
}
for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value


import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from src.config import get_settings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _reset_settings_cache() -> None:
    """Force Settings to rebuild against the test env injected above."""
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def app_with_lifespan() -> AsyncGenerator[FastAPI]:
    """Yield the FastAPI app with its real lifespan (Redis/Milvus connected).

    Per-test scope so each test starts and ends with the connect/disconnect
    cycle exercised end-to-end.
    """
    from src.main import app

    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture
async def client(app_with_lifespan: FastAPI) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app_with_lifespan)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Direct SQLAlchemy session for tests that don't need the full app."""
    from src.db.session import async_session_factory

    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
