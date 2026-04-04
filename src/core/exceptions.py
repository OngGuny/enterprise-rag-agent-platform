from typing import Any


class AppException(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        detail: str = "An unexpected error occurred",
        *,
        context: dict[str, Any] | None = None,
    ):
        self.detail = detail
        self.context = context or {}
        super().__init__(detail)


class ValidationError(AppException):
    status_code = 400
    error_code = "VALIDATION_ERROR"


class NotFoundError(AppException):
    status_code = 404
    error_code = "NOT_FOUND"


class ConflictError(AppException):
    status_code = 409
    error_code = "CONFLICT"


class RateLimitExceededError(AppException):
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"


class ExternalServiceError(AppException):
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"


class LLMServiceError(ExternalServiceError):
    error_code = "LLM_SERVICE_ERROR"


class MilvusServiceError(ExternalServiceError):
    error_code = "MILVUS_SERVICE_ERROR"


class EmbeddingServiceError(ExternalServiceError):
    error_code = "EMBEDDING_SERVICE_ERROR"
