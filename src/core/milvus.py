from pymilvus import MilvusClient

from src.core.logging import get_logger

logger = get_logger(__name__)


class MilvusManager:
    _client: MilvusClient | None = None

    @classmethod
    def connect(cls, uri: str) -> None:
        cls._client = MilvusClient(uri=uri)
        collections = cls._client.list_collections()
        logger.info("milvus_connected", uri=uri, collections=collections)

    @classmethod
    def get_client(cls) -> MilvusClient:
        if cls._client is None:
            raise RuntimeError("Milvus not connected. Call MilvusManager.connect() first.")
        return cls._client

    @classmethod
    def disconnect(cls) -> None:
        if cls._client:
            cls._client.close()
            cls._client = None
            logger.info("milvus_disconnected")
