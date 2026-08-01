"""Human console auth: dev login + optional OIDC-shaped sessions (C3).

API keys remain for automation. Browser sessions carry role + tenant membership.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

from fastapi import Header, HTTPException, Request

Role = Literal["operator", "reviewer", "admin"]
_VALID_ROLES = frozenset({"operator", "reviewer", "admin"})


@dataclass(frozen=True)
class ConsoleUser:
    user_id: str
    display_name: str
    roles: frozenset[str]
    tenants: tuple[str, ...]
    active_tenant: str

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    def may(self, role: Role) -> bool:
        if self.is_admin:
            return True
        order = {"operator": 1, "reviewer": 2, "admin": 3}
        have = max((order.get(r, 0) for r in self.roles), default=0)
        # reviewer implies operator read/write for Pilot; admin implies all
        if role == "operator":
            return have >= 1 or "operator" in self.roles or "reviewer" in self.roles
        if role == "reviewer":
            return "reviewer" in self.roles or self.is_admin
        return self.is_admin


class SessionStore:
    """Signed cookie sessions (HMAC) — no server DB required for C3."""

    def __init__(self, secret: str | None = None) -> None:
        self.secret = (
            secret
            or os.environ.get("RECERTIA_CONSOLE_SESSION_SECRET")
            or secrets.token_hex(32)
        ).encode()

    def issue(self, user: ConsoleUser, *, ttl_s: int = 86400) -> str:
        payload = {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "roles": sorted(user.roles),
            "tenants": list(user.tenants),
            "active_tenant": user.active_tenant,
            "exp": int(time.time()) + ttl_s,
        }
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        sig = hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def parse(self, token: str | None) -> ConsoleUser | None:
        if not token or "." not in token:
            return None
        body, _, sig = token.rpartition(".")
        expect = hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return None
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        tenants = tuple(payload.get("tenants") or [])
        if not tenants:
            return None
        active = payload.get("active_tenant") or tenants[0]
        if active not in tenants:
            active = tenants[0]
        roles = frozenset(payload.get("roles") or [])
        if not roles & _VALID_ROLES:
            return None
        return ConsoleUser(
            user_id=str(payload["user_id"]),
            display_name=str(payload.get("display_name") or payload["user_id"]),
            roles=roles,
            tenants=tenants,
            active_tenant=str(active),
        )

    def switch_tenant(self, user: ConsoleUser, tenant_id: str) -> ConsoleUser:
        if tenant_id not in user.tenants:
            raise ValueError("tenant not in membership")
        return ConsoleUser(
            user_id=user.user_id,
            display_name=user.display_name,
            roles=user.roles,
            tenants=user.tenants,
            active_tenant=tenant_id,
        )


def auth_mode() -> str:
    return os.environ.get("RECERTIA_CONSOLE_AUTH", "dev").strip().lower() or "dev"


def oidc_configured() -> bool:
    return bool(
        os.environ.get("RECERTIA_OIDC_ISSUER")
        and os.environ.get("RECERTIA_OIDC_CLIENT_ID")
        and os.environ.get("RECERTIA_OIDC_CLIENT_SECRET")
    )


def oidc_authorize_url(*, redirect_uri: str, state: str) -> str:
    issuer = os.environ["RECERTIA_OIDC_ISSUER"].rstrip("/")
    client_id = os.environ["RECERTIA_OIDC_CLIENT_ID"]
    scope = os.environ.get("RECERTIA_OIDC_SCOPE", "openid profile email")
    qs = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
        }
    )
    return f"{issuer}/authorize?{qs}"


def oidc_exchange_code(*, code: str, redirect_uri: str) -> ConsoleUser:
    """Exchange auth code for tokens and map to ConsoleUser (generic OIDC)."""

    issuer = os.environ["RECERTIA_OIDC_ISSUER"].rstrip("/")
    token_url = os.environ.get("RECERTIA_OIDC_TOKEN_URL", f"{issuer}/token")
    userinfo_url = os.environ.get("RECERTIA_OIDC_USERINFO_URL", f"{issuer}/userinfo")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": os.environ["RECERTIA_OIDC_CLIENT_ID"],
        "client_secret": os.environ["RECERTIA_OIDC_CLIENT_SECRET"],
    }
    try:
        tok_req = urllib.request.Request(
            token_url,
            data=urllib.parse.urlencode(data).encode(),
            headers={"content-type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(tok_req, timeout=30) as resp:
            tok_payload = json.loads(resp.read().decode())
        access = tok_payload.get("access_token")
        if not access:
            raise HTTPException(status_code=502, detail="oidc token missing access_token")
        info_req = urllib.request.Request(
            userinfo_url,
            headers={"authorization": f"Bearer {access}"},
            method="GET",
        )
        with urllib.request.urlopen(info_req, timeout=30) as resp:
            profile = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"oidc exchange failed: {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"oidc network error: {exc}") from exc
    user_id = str(profile.get("sub") or profile.get("email") or "")
    if not user_id:
        raise HTTPException(status_code=502, detail="oidc userinfo missing sub")
    roles_raw = profile.get("roles") or os.environ.get("RECERTIA_OIDC_DEFAULT_ROLES", "operator")
    if isinstance(roles_raw, str):
        roles = frozenset(r.strip() for r in roles_raw.split(",") if r.strip())
    else:
        roles = frozenset(str(r) for r in roles_raw)
    tenants_raw = profile.get("tenants") or os.environ.get(
        "RECERTIA_OIDC_DEFAULT_TENANTS", "default"
    )
    if isinstance(tenants_raw, str):
        tenants = tuple(t.strip() for t in tenants_raw.split(",") if t.strip())
    else:
        tenants = tuple(str(t) for t in tenants_raw)
    return ConsoleUser(
        user_id=user_id,
        display_name=str(profile.get("name") or profile.get("email") or user_id),
        roles=roles or frozenset({"operator"}),
        tenants=tenants or ("default",),
        active_tenant=(tenants or ("default",))[0],
    )


def require_console_user(
    request: Request,
    sessions: SessionStore,
    *,
    min_role: Role = "operator",
    x_recertia_session: str | None = Header(default=None, alias="X-Recertia-Session"),
    x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
) -> ConsoleUser:
    token = x_recertia_session or request.cookies.get("recertia_session")
    user = sessions.parse(token)
    if user is None:
        raise HTTPException(status_code=401, detail="console authentication required")
    if not user.may(min_role):
        raise HTTPException(status_code=403, detail=f"requires role {min_role}")
    if x_recertia_tenant:
        if x_recertia_tenant not in user.tenants:
            raise HTTPException(status_code=403, detail="tenant not in membership")
        user = sessions.switch_tenant(user, x_recertia_tenant)
    return user
