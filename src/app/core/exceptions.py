"""Application-wide exception types and FastAPI handlers."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse


class AppException(Exception):
    """Base app exception. Server returns code + English message; client maps to locale."""

    code: str = "INTERNAL_ERROR"
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


# Common subclasses
class NotFoundError(AppException):
    code = "NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Resource not found"


class ValidationError(AppException):
    code = "VALIDATION_ERROR"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "Validation failed"


class UnauthorizedError(AppException):
    code = "UNAUTHORIZED"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Authentication required"


class ForbiddenError(AppException):
    code = "FORBIDDEN"
    status_code = status.HTTP_403_FORBIDDEN
    message = "Permission denied"


class ConflictError(AppException):
    code = "CONFLICT"
    status_code = status.HTTP_409_CONFLICT
    message = "Resource conflict"


class RateLimitError(AppException):
    code = "RATE_LIMIT"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Rate limit exceeded"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def _app_exc(_req: Request, exc: AppException) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _val_exc(_req: Request, exc: RequestValidationError) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Validation failed",
                    "details": {"errors": jsonable_encoder(exc.errors())},
                }
            },
        )
