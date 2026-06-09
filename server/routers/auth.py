"""Authentication endpoints for the thin app-level login layer."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from server.lib import auth
from server.lib.repository import users as users_repo

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class UserInfo(BaseModel):
    email: str
    name: str
    role: str
    tenant_id: str | None = None


def _is_https(request: Request) -> bool:
    # Databricks Apps terminates TLS at the proxy and forwards X-Forwarded-Proto.
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


@router.post("/login", response_model=UserInfo)
async def login(req: LoginRequest, request: Request, response: Response) -> UserInfo:
    try:
        user = users_repo.get_by_email(req.email)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"auth store unavailable: {e}")

    if not user or not auth.verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = auth.make_session(
        email=user.email, role=user.role, tenant_id=user.tenant_id, name=user.display_name
    )
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=token,
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path="/",
    )
    try:
        users_repo.touch_login(user.email)
    except Exception:
        pass
    return UserInfo(
        email=user.email, name=user.display_name, role=user.role, tenant_id=user.tenant_id
    )


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserInfo)
async def me(request: Request) -> UserInfo:
    user = auth.current_user(request)
    return UserInfo(
        email=user["email"],
        name=user.get("name", user["email"]),
        role=user.get("role", "user"),
        tenant_id=user.get("tenant_id"),
    )


class DemoAccount(BaseModel):
    email: str
    name: str
    role: str
    tenant_id: str | None = None


@router.get("/demo-accounts", response_model=list[DemoAccount])
async def demo_accounts() -> list[DemoAccount]:
    """Unauthenticated helper for the login screen: surface the seeded
    login→client mapping so the demo is self-explanatory. Returns no secrets,
    and only the small set of seeded demo logins (all share the demo password).
    Operator first, then client logins sorted by name.
    """
    try:
        rows = users_repo.list_all()
    except Exception:
        return []
    accounts = [
        DemoAccount(
            email=r.email, name=r.display_name, role=r.role, tenant_id=r.tenant_id
        )
        for r in rows
    ]
    accounts.sort(key=lambda a: (a.role != "operator", a.name.lower()))
    return accounts[:12]
