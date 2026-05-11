"""Exception handlers should normalize errors into the {error: {code, message}} envelope.

Why this matters: ADR-002/003 lean on a stable error shape so that downstream
clients (and the eventual agent layer) can reason about failure modes without
sniffing raw stack traces.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from httpx import AsyncClient

from src.core.exceptions import AppException, NotFoundError

pytestmark = pytest.mark.integration


def _attach_debug_routes(app: FastAPI) -> None:
    debug_router = APIRouter()

    @debug_router.get("/__test/app-exception")
    async def _raise_app_exc() -> None:
        raise NotFoundError(detail="document not found", context={"id": "abc"})

    @debug_router.get("/__test/unhandled")
    async def _raise_unhandled() -> None:
        raise ValueError("boom")

    @debug_router.get("/__test/custom-app-exc")
    async def _raise_custom() -> None:
        class _Custom(AppException):
            status_code = 418
            error_code = "TEAPOT"

        raise _Custom(detail="i am a teapot")

    app.include_router(debug_router, prefix="/api/v1")


async def test_app_exception_serialized_with_error_envelope(
    client: AsyncClient, app_with_lifespan: FastAPI
) -> None:
    _attach_debug_routes(app_with_lifespan)
    response = await client.get("/api/v1/__test/app-exception")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "document not found"}}


async def test_unhandled_exception_returns_generic_500(
    client: AsyncClient, app_with_lifespan: FastAPI
) -> None:
    _attach_debug_routes(app_with_lifespan)
    response = await client.get("/api/v1/__test/unhandled")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    # Internal errors must not leak the original exception message.
    assert "boom" not in body["error"]["message"]


async def test_custom_app_exception_subclass_uses_its_status_and_code(
    client: AsyncClient, app_with_lifespan: FastAPI
) -> None:
    _attach_debug_routes(app_with_lifespan)
    response = await client.get("/api/v1/__test/custom-app-exc")
    assert response.status_code == 418
    assert response.json() == {"error": {"code": "TEAPOT", "message": "i am a teapot"}}
