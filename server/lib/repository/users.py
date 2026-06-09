"""app_users CRUD against Lakebase / local Postgres."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from server.lib import db


@dataclass(frozen=True)
class UserRow:
    id: int
    email: str
    password_hash: str
    display_name: str
    tenant_id: Optional[str]
    role: str
    created_at: datetime
    last_login_at: Optional[datetime]


_COLS = (
    "id, email, password_hash, display_name, tenant_id, role, "
    "created_at, last_login_at"
)


def _row(r) -> UserRow:
    return UserRow(
        id=r[0],
        email=r[1],
        password_hash=r[2],
        display_name=r[3],
        tenant_id=r[4],
        role=r[5],
        created_at=r[6],
        last_login_at=r[7],
    )


def get_by_email(email: str) -> Optional[UserRow]:
    with db.get_connection() as conn:
        cur = conn.execute(
            f"SELECT {_COLS} FROM app_users WHERE LOWER(email) = LOWER(%s)",
            (email,),
        )
        row = cur.fetchone()
        return _row(row) if row else None


def list_all() -> list[UserRow]:
    with db.get_connection() as conn:
        cur = conn.execute(
            f"SELECT {_COLS} FROM app_users ORDER BY role DESC, email"
        )
        return [_row(r) for r in cur.fetchall()]


def count() -> int:
    with db.get_connection() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM app_users")
        return int(cur.fetchone()[0])


def upsert(
    *,
    email: str,
    password_hash: str,
    display_name: str,
    tenant_id: Optional[str],
    role: str = "user",
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO app_users (email, password_hash, display_name, tenant_id, role) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (email) DO UPDATE SET "
            "  password_hash = EXCLUDED.password_hash, "
            "  display_name = EXCLUDED.display_name, "
            "  tenant_id = EXCLUDED.tenant_id, "
            "  role = EXCLUDED.role",
            (email.lower(), password_hash, display_name, tenant_id, role),
        )
        conn.commit()


def touch_login(email: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE app_users SET last_login_at = NOW() WHERE LOWER(email) = LOWER(%s)",
            (email,),
        )
        conn.commit()
