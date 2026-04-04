from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import DbDep, MilvusDep, RedisDep

router = APIRouter()


@router.get("/")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(db: DbDep, redis: RedisDep, milvus: MilvusDep) -> JSONResponse:
    checks = {
        "database": await _check_db(db),
        "redis": await _check_redis(redis),
        "milvus": _check_milvus(milvus),
    }
    all_healthy = all(c["status"] == "ok" for c in checks.values())
    return JSONResponse(
        content={
            "status": "ready" if all_healthy else "degraded",
            "checks": checks,
        },
        status_code=200 if all_healthy else 503,
    )


async def _check_db(db: AsyncSession) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


async def _check_redis(redis: Redis) -> dict[str, str]:
    try:
        await redis.ping()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _check_milvus(milvus: object) -> dict[str, str]:
    try:
        from pymilvus import MilvusClient

        if isinstance(milvus, MilvusClient):
            milvus.list_collections()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
