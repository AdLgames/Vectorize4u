"""RFC 9457 `application/problem+json`.

Stable `error_code` strings, and a hard separation between 400 (the image is
the problem) and 500 (we are the problem). The worker's retry logic and the
alerting both key on that split (§3.5), so it must survive the trip through
HTTP intact.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

PROBLEM_TYPE = "https://docs.vectorize.example/errors/{code}"


class ProblemError(HTTPException):
    def __init__(
        self,
        status_code: int,
        error_code: str,
        detail: str,
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.error_code = error_code
        self.extra = extra or {}


def problem_response(request: Request, exc: ProblemError) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_TYPE.format(code=exc.error_code),
        "title": exc.error_code.replace("_", " "),
        "status": exc.status_code,
        "detail": exc.detail,
        "instance": str(request.url.path),
        "error_code": exc.error_code,
    }
    body.update(exc.extra)
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=exc.headers,
        media_type="application/problem+json",
    )


def http_exception_response(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc, ProblemError):
        return problem_response(request, exc)
    code = {
        400: "bad_request", 401: "unauthorized", 402: "payment_required",
        403: "forbidden", 404: "not_found", 409: "conflict", 413: "payload_too_large",
        415: "unsupported_media_type", 422: "unprocessable", 429: "rate_limited",
    }.get(exc.status_code, "error")
    headers = dict(exc.headers) if exc.headers else None
    return problem_response(
        request, ProblemError(exc.status_code, code, str(exc.detail), headers=headers)
    )


def bad_image(detail: str, code: str = "bad_image") -> ProblemError:
    return ProblemError(400, code, detail)


def not_found(what: str) -> ProblemError:
    return ProblemError(404, "not_found", f"no such {what}")


def unauthorized(detail: str = "authentication required") -> ProblemError:
    return ProblemError(401, "unauthorized", detail, headers={"WWW-Authenticate": "Bearer"})


def forbidden(detail: str) -> ProblemError:
    return ProblemError(403, "forbidden", detail)


def payment_required(detail: str, *, balance: int = 0) -> ProblemError:
    return ProblemError(402, "insufficient_credits", detail, extra={"credits_remaining": balance})


def rate_limited(retry_after: int, detail: str = "too many requests") -> ProblemError:
    return ProblemError(
        429, "rate_limited", detail, headers={"Retry-After": str(retry_after)}
    )


def too_large(detail: str) -> ProblemError:
    return ProblemError(413, "image_too_large", detail)


def conflict(code: str, detail: str) -> ProblemError:
    return ProblemError(409, code, detail)


def internal(code: str = "internal_error", detail: str = "internal error") -> ProblemError:
    return ProblemError(500, code, detail)
