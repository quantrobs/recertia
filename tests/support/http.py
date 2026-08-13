"""HTTP error body helpers (envelope or FastAPI ``detail``)."""

from __future__ import annotations

from typing import Any


def error_text(response: Any) -> str:
    """Return the human message from a ``/v1`` envelope or a ``{detail}`` body."""

    body = response.json()
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message") is not None:
            return str(err["message"])
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
    return response.text
