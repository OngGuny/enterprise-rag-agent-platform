from redis.asyncio import ConnectionPool, Redis

from src.core.logging import get_logger

logger = get_logger(__name__)


class RedisManager:
    _pool: ConnectionPool | None = None

    @classmethod
    async def connect(cls, url: str, max_connections: int = 50) -> None:
        cls._pool = ConnectionPool.from_url(
            url,
            max_connections=max_connections,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
        )
        client = Redis(connection_pool=cls._pool)
        await client.ping()
        await client.aclose()
        logger.info("redis_connected", url=url.split("@")[-1])

    @classmethod
    def get_client(cls) -> Redis:
        if cls._pool is None:
            raise RuntimeError("Redis not connected. Call RedisManager.connect() first.")
        return Redis(connection_pool=cls._pool)

    @classmethod
    async def disconnect(cls) -> None:
        if cls._pool:
            await cls._pool.disconnect()
            cls._pool = None
            logger.info("redis_disconnected")
