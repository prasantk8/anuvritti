"""DomainError -> HTTP status, in exactly one place.

docs/contracts/errors.md is the contract; this table is its only implementation. Clients
switch on `code`, so the status is a convenience and the code is the promise.
"""

from __future__ import annotations

from typing import Final

from fastapi.responses import JSONResponse

from anuvritti.shared.errors import DomainError, ErrorCode

STATUS_BY_CODE: Final[dict[ErrorCode, int]] = {
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.FAMILY_NOT_FOUND: 404,
    ErrorCode.MEMBER_NOT_FOUND: 404,
    ErrorCode.CHILD_NOT_FOUND: 404,
    ErrorCode.SPARK_NOT_FOUND: 404,
    ErrorCode.MOMENT_NOT_FOUND: 404,
    ErrorCode.MEDIA_NOT_FOUND: 404,
    ErrorCode.SPARK_INVALID_TRANSITION: 409,
    ErrorCode.SPARK_ARCHIVED: 409,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.PAIRING_FAILED: 401,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.CAPTURE_SOURCE_INVALID: 422,
    ErrorCode.MEDIA_TOO_LARGE: 413,
    ErrorCode.MEDIA_KIND_UNSUPPORTED: 415,
    ErrorCode.CONFLICT: 409,
}


def status_for(error: DomainError) -> int:
    return STATUS_BY_CODE.get(error.code, 500)


def error_response(error: DomainError) -> JSONResponse:
    return JSONResponse(status_code=status_for(error), content=error.to_dict())
