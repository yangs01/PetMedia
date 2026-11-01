"""Application error hierarchy.

``AppError`` subclasses carry the stable error code and HTTP status used by the
API error format. Provider errors separate transient failures (safe to retry)
from permanent ones (retrying cannot help, such as an invalid API key).
"""

from typing import Any

from sqlalchemy.exc import DBAPIError, OperationalError


class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"

    def __init__(
        self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class RequestValidationFailure(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class InvalidTaskStateError(ConflictError):
    code = "INVALID_TASK_STATE"


class StaleReviewError(ConflictError):
    code = "STALE_REVIEW"


class DuplicateDecisionError(ConflictError):
    code = "DUPLICATE_DECISION"


class ExportNotReadyError(ConflictError):
    code = "EXPORT_NOT_READY"


class MediaError(AppError):
    status_code = 422
    code = "MEDIA_ERROR"


class MediaFileMissingError(AppError):
    status_code = 500
    code = "MEDIA_FILE_MISSING"


class AuthenticationError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class WorkflowError(AppError):
    """Unexpected graph or business inconsistency. Retrying will not fix it."""

    code = "WORKFLOW_ERROR"


class ProviderError(AppError):
    status_code = 502
    code = "PROVIDER_ERROR"


class ProviderNotConfiguredError(ProviderError):
    code = "PROVIDER_NOT_CONFIGURED"


class ProviderPermanentError(ProviderError):
    """Bad credentials, rejected request, content refusal: do not retry."""


class ProviderTransientError(ProviderError):
    """Timeout, rate limit or temporary server failure: retry with backoff."""

    code = "PROVIDER_TRANSIENT_ERROR"


class StructuredOutputError(ProviderError):
    """The model kept returning output that fails schema validation."""

    code = "INVALID_STRUCTURED_OUTPUT"


def is_transient_error(error: BaseException) -> bool:
    """Decide whether an operation that raised ``error`` is worth retrying."""
    if isinstance(error, ProviderTransientError | OperationalError):
        return True
    return isinstance(error, DBAPIError) and error.connection_invalidated
