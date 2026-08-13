"""Stable ``/v1`` error envelope (remaining-work RW-SUR)."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

_RETRYABLE_CODES = frozenset({"rate_limited", "lock_timeout", "worker_busy"})


def error_body(
    *,
    code: str,
    message: str,
    run_id: str | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    if retryable is None:
        retryable = code in _RETRYABLE_CODES
    err: dict[str, Any] = {"code": code, "message": message, "retryable": bool(retryable)}
    if run_id:
        err["run_id"] = run_id
    return {"error": err}


def v1_error(
    status_code: int,
    *,
    code: str,
    message: str,
    run_id: str | None = None,
    retryable: bool | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(code=code, message=message, run_id=run_id, retryable=retryable),
    )


class V1HTTPError(Exception):
    """Raise from new ``/v1`` routes so the envelope is used instead of FastAPI ``detail``."""

    def __init__(
        self,
        status_code: int,
        *,
        code: str,
        message: str,
        run_id: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.run_id = run_id
        self.retryable = retryable

    def response(self) -> JSONResponse:
        return v1_error(
            self.status_code,
            code=self.code,
            message=self.message,
            run_id=self.run_id,
            retryable=self.retryable,
        )
