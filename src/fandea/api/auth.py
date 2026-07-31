"""Single-host API-key authentication with scoped tenant principals."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Callable

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class Principal:
    key_id: str
    tenant_id: str
    scopes: frozenset[str]


def _configured_key() -> str:
    key = os.environ.get("FANDEA_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="API key authentication is not configured")
    return key


def require_key(
    required_scope: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Principal:
    expected = _configured_key()
    if x_api_key is None or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid API key")
    scopes = frozenset(os.environ.get("FANDEA_API_SCOPES", "runs,blobs,metrics,admin").split(","))
    if required_scope not in scopes and "admin" not in scopes:
        raise HTTPException(status_code=403, detail=f"missing scope: {required_scope}")
    return Principal(
        key_id=hashlib.sha256(expected.encode()).hexdigest()[:12],
        tenant_id=os.environ.get("FANDEA_TENANT_ID", "single-host"),
        scopes=scopes,
    )


def require_scope(scope: str) -> Callable[..., Principal]:
    """FastAPI dependency factory preserving the header parameter signature."""

    def dependency(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> Principal:
        return require_key(scope, x_api_key)

    return dependency
