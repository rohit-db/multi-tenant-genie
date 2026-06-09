"""Thin app-level authentication: password hashing, signed session cookies,
and FastAPI dependencies.

This is the SaaS's *own* user directory and session layer — deliberately
separate from Databricks workspace identity. It models how a real embedded
analytics product gates its end users before the backend ever touches
Databricks (where the per-tenant Service Principal + UC row filter take over).

No third-party crypto deps: PBKDF2-HMAC-SHA256 for passwords, HMAC-SHA256 for
session signing — both from the standard library.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional

from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)

COOKIE_NAME = "mtg_session"
SESSION_TTL_SECONDS = 60 * 60 * 12  # 12h
_PBKDF2_ITERATIONS = 200_000

# Tests run the routers through TestClient without a session; this flag makes
# `current_user` return a synthetic operator so the suite doesn't need cookies.
_AUTH_DISABLED = bool(os.getenv("MT_GENIE_AUTH_DISABLED"))


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return (
        f"pbkdf2_sha256${_PBKDF2_ITERATIONS}$"
        f"{base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ---------------------------------------------------------------- session
def _secret() -> bytes:
    """Signing secret. Prefer an explicit secret; otherwise derive a stable
    one from the AES key (already bound in Apps) so sessions survive restarts.
    """
    explicit = os.getenv("MT_GENIE_SESSION_SECRET")
    if explicit:
        return explicit.encode()
    aes = os.getenv("AES_KEY_BASE64")
    if aes:
        return hashlib.sha256(b"mtg-session:" + aes.encode()).digest()
    # Last resort: ephemeral per-process secret (sessions drop on restart).
    global _EPHEMERAL
    try:
        return _EPHEMERAL  # type: ignore[name-defined]
    except NameError:
        logger.warning(
            "No MT_GENIE_SESSION_SECRET or AES_KEY_BASE64 — using an ephemeral "
            "session secret; sessions will not survive a restart."
        )
        _EPHEMERAL = secrets.token_bytes(32)  # noqa: F841
        return _EPHEMERAL


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_session(
    *, email: str, role: str, tenant_id: Optional[str], name: str
) -> str:
    payload = {
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "name": name,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64u(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def parse_session(token: str) -> Optional[dict]:
    try:
        body, sig = token.split(".")
        expected = _b64u(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64u_decode(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ---------------------------------------------------------------- deps
def current_user(request: Request) -> dict:
    if _AUTH_DISABLED:
        return {"email": "test@local", "role": "operator", "tenant_id": None, "name": "Test"}
    token = request.cookies.get(COOKIE_NAME)
    payload = parse_session(token) if token else None
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return payload


def require_operator(request: Request) -> dict:
    user = current_user(request)
    if user.get("role") != "operator":
        raise HTTPException(status_code=403, detail="Operator access required")
    return user


# ---------------------------------------------------------------- seeding
def seed_demo_users() -> None:
    """Seed the app user directory with a login→client mapping. Idempotent.

    Layout:
      - ``operator@skydesk.app`` — global operator (no tenant binding); can
        switch workspaces and reach the console.
      - one customer login **per active tenant**: ``<tenant_id>@skydesk.app``,
        bound to that tenant. This is the login→client mapping: signing in as
        that user pins the whole product to that client.
      - ``analyst@skydesk.app`` — kept as a friendly alias bound to the first
        active tenant, so the documented demo login is a real customer login.

    All accounts share ``MT_GENIE_DEMO_PASSWORD`` (default 'skydesk'). Runs on
    every boot and upserts, so newly-onboarded tenants get a login automatically
    on the next restart.
    """
    from server.lib.repository import users as users_repo, tenant as tenant_repo

    pw = os.getenv("MT_GENIE_DEMO_PASSWORD", "skydesk")

    def _seed(email: str, display_name: str, tenant_id: Optional[str], role: str) -> None:
        try:
            users_repo.upsert(
                email=email,
                password_hash=hash_password(pw),
                display_name=display_name,
                tenant_id=tenant_id,
                role=role,
            )
            logger.info("Seeded user %s (role=%s, tenant=%s)", email, role, tenant_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed seeding %s: %s", email, e)

    # Global operator.
    _seed("operator@skydesk.app", "SkyDesk Operator", None, "operator")

    # One bound customer login per active tenant.
    try:
        tenants = [t for t in tenant_repo.list_all() if t.status == "active"]
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not list tenants for login seeding: %s", e)
        tenants = []

    for t in tenants:
        _seed(
            f"{t.tenant_id}@skydesk.app",
            f"{t.display_name} Analyst",
            t.tenant_id,
            "user",
        )

    # Friendly alias bound to the first active tenant.
    if tenants:
        first = tenants[0]
        _seed(
            "analyst@skydesk.app",
            f"{first.display_name} Analyst",
            first.tenant_id,
            "user",
        )
