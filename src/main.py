from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.router import api_router
from src.config import get_settings
from src.core.exceptions import AppException
from src.core.logging import get_logger, setup_logging
from src.core.milvus import MilvusManager
from src.core.redis import RedisManager
from src.db.session import engine

settings = get_settings()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging(log_level=settings.log_level, json_format=not settings.debug)

    await RedisManager.connect(settings.redis_url, settings.redis_max_connections)

    try:
        MilvusManager.connect(settings.milvus_uri)
    except Exception:
        logger.warning("milvus_connection_failed", uri=settings.milvus_uri)

    logger.info("startup_complete")
    yield

    MilvusManager.disconnect()
    await RedisManager.disconnect()
    await engine.dispose()
    logger.info("shutdown_complete")


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    logger.error(
        "app_error",
        error_code=exc.error_code,
        status_code=exc.status_code,
        detail=exc.detail,
        path=str(request.url),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.error_code, "message": exc.detail}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", path=str(request.url))
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}},
    )
