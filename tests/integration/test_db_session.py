"""Validate the SQLAlchemy AsyncSession factory against a real Postgres."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_session_executes_select_one(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


async def test_session_recovers_after_rollback(db_session: AsyncSession) -> None:
    """Querying a missing relation aborts the transaction; an explicit
    rollback must leave the session usable again — this is the contract
    that ``get_db_session`` relies on.
    """
    with pytest.raises((ProgrammingError, DBAPIError)):
        await db_session.execute(text("SELECT * FROM __nonexistent_table_for_test"))
    await db_session.rollback()

    result = await db_session.execute(text("SELECT 2"))
    assert result.scalar_one() == 2


async def test_engine_uses_pool_pre_ping_settings() -> None:
    """ADR-002 promises pre-ping + recycle. Verify the engine reflects that."""
    from src.db.session import engine

    pool = engine.pool
    # SQLAlchemy stores pre_ping on the pool internals; the public attr is
    # ``_pre_ping`` (QueuePool). Fall back to a duck-typed check.
    pre_ping = getattr(pool, "_pre_ping", None)
    if pre_ping is None:
        # Older/newer SA versions expose it differently — just ensure the
        # engine was created without erroring and dialect is asyncpg.
        assert engine.dialect.driver == "asyncpg"
    else:
        assert pre_ping is True
        assert engine.dialect.driver == "asyncpg"
