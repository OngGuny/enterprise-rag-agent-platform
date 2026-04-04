from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from pymilvus import MilvusClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.core.milvus import MilvusManager
from src.core.redis import RedisManager
from src.db.session import get_db_session

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


async def get_redis() -> Redis:
    return RedisManager.get_client()


async def get_milvus() -> MilvusClient:
    return MilvusManager.get_client()


DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
MilvusDep = Annotated[MilvusClient, Depends(get_milvus)]
