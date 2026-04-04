from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    app_name: str = "Enterprise RAG Agent Platform"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/ragplatform"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30

    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50

    milvus_uri: str = "http://localhost:19530"
    milvus_default_collection: str = "documents"

    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    vllm_base_url: str = "http://localhost:8001/v1"
    default_model: str = "gpt-4o-mini"

    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024

    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    cors_origins: list[str] = ["*"]

    rate_limit_rate: float = 10.0
    rate_limit_capacity: int = 20

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper


@lru_cache
def get_settings() -> Settings:
    return Settings()
