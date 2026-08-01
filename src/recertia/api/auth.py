"""Durable, scoped API-key authentication."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import Header, HTTPException

_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_ALLOWED_SCOPES = frozenset({"runs", "blobs", "metrics", "admin"})


@dataclass(frozen=True)
class Principal:
    key_id: str
    tenant_id: str
    scopes: frozenset[str]


@dataclass(frozen=True)
class IssuedApiKey:
    key_id: str
    secret: str
    tenant_id: str
    scopes: frozenset[str]


def validate_tenant_id(tenant_id: str) -> str:
    if not _TENANT_ID_RE.fullmatch(tenant_id):
        raise ValueError(
            "tenant_id must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ "
            "(no path separators or traversal)"
        )
    return tenant_id


def validate_scopes(scopes: set[str] | frozenset[str]) -> frozenset[str]:
    normalized = frozenset(scopes)
    if not normalized:
        raise ValueError("at least one scope is required")
    unknown = normalized - _ALLOWED_SCOPES
    if unknown:
        raise ValueError(f"unknown scopes: {sorted(unknown)}")
    if any("," in scope or scope != scope.strip() or not scope for scope in normalized):
        raise ValueError("scopes must be allowlisted tokens without commas or whitespace")
    return normalized


class ApiKeyStore:
    """SQLite-backed key registry. Only salted PBKDF2 hashes are persisted."""

    _ITERATIONS = 600_000

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    salt BLOB NOT NULL,
                    key_hash BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    revoked_by TEXT
                );
                CREATE TABLE IF NOT EXISTS api_key_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    key_id TEXT,
                    actor TEXT NOT NULL,
                    detail TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _hash(cls, secret: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, cls._ITERATIONS)

    def _audit(
        self,
        conn: sqlite3.Connection,
        action: str,
        *,
        key_id: str | None,
        actor: str,
        detail: str,
    ) -> None:
        conn.execute(
            "INSERT INTO api_key_audit(at, action, key_id, actor, detail) VALUES (?, ?, ?, ?, ?)",
            (self._now(), action, key_id, actor, detail),
        )

    def issue(self, *, tenant_id: str, scopes: set[str] | frozenset[str], actor: str) -> IssuedApiKey:
        tenant_id = validate_tenant_id(tenant_id)
        scopes = validate_scopes(scopes)
        key_id = f"key_{secrets.token_hex(8)}"
        secret = f"fnd_{secrets.token_urlsafe(32)}"
        salt = secrets.token_bytes(16)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO api_keys(key_id, tenant_id, scopes, salt, key_hash, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    key_id,
                    tenant_id,
                    ",".join(sorted(scopes)),
                    salt,
                    self._hash(secret, salt),
                    self._now(),
                ),
            )
            self._audit(conn, "issued", key_id=key_id, actor=actor, detail=f"tenant={tenant_id}")
        return IssuedApiKey(key_id, secret, tenant_id, scopes)

    def authenticate(self, secret: str | None) -> Principal | None:
        if not secret:
            return None
        # Key IDs are intentionally not encoded in the bearer secret. Scan active
        # records so lookup itself does not disclose a valid key identifier.
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key_id, tenant_id, scopes, salt, key_hash FROM api_keys WHERE revoked_at IS NULL"
            ).fetchall()
            for key_id, tenant_id, scopes, salt, stored_hash in rows:
                if hmac.compare_digest(self._hash(secret, salt), stored_hash):
                    try:
                        validate_tenant_id(tenant_id)
                        scope_set = validate_scopes(set(scopes.split(",")))
                    except ValueError:
                        self._audit(
                            conn,
                            "authentication_failed",
                            key_id=key_id,
                            actor=key_id,
                            detail="invalid tenant or scopes",
                        )
                        return None
                    self._audit(conn, "authenticated", key_id=key_id, actor=key_id, detail="success")
                    return Principal(key_id=key_id, tenant_id=tenant_id, scopes=scope_set)
            self._audit(
                conn, "authentication_failed", key_id=None, actor="anonymous", detail="invalid key"
            )
        return None

    def revoke(self, key_id: str, *, actor: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE api_keys SET revoked_at=?, revoked_by=? WHERE key_id=? AND revoked_at IS NULL",
                (self._now(), actor, key_id),
            )
            if cursor.rowcount:
                self._audit(conn, "revoked", key_id=key_id, actor=actor, detail="revoked")
                return True
        return False

    def list_keys(self) -> list[dict[str, str | bool]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key_id, tenant_id, scopes, created_at, revoked_at FROM api_keys ORDER BY created_at"
            ).fetchall()
        return [
            {
                "key_id": row[0],
                "tenant_id": row[1],
                "scopes": row[2],
                "created_at": row[3],
                "revoked": bool(row[4]),
            }
            for row in rows
        ]


def require_key(
    required_scope: str,
    store: ApiKeyStore,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Principal:
    principal = store.authenticate(x_api_key)
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    if required_scope not in principal.scopes and "admin" not in principal.scopes:
        raise HTTPException(status_code=403, detail=f"missing scope: {required_scope}")
    return principal


def require_scope(scope: str, store: ApiKeyStore) -> Callable[..., Principal]:
    """FastAPI dependency factory preserving the header parameter signature."""

    def dependency(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> Principal:
        return require_key(scope, store, x_api_key)

    return dependency
