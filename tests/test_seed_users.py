"""Tests for the login→client seeding in server.lib.auth.seed_demo_users.

Requires `docker compose up -d` (Postgres on :5432). Skipped otherwise.
"""
import pytest
import psycopg

from server.lib import auth, db
from server.lib.repository import tenant as tenant_repo, users as users_repo

LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/mtg"


def _can_connect() -> bool:
    try:
        with psycopg.connect(LOCAL_DB, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _can_connect(), reason="Local Postgres not running"
)


@pytest.fixture
def fresh_db(monkeypatch):
    with psycopg.connect(LOCAL_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", LOCAL_DB)
    monkeypatch.setenv("MT_GENIE_DEMO_PASSWORD", "skydesk")
    db.apply_migrations("sql/lakebase")
    yield


def test_seeds_operator_and_per_tenant_logins(fresh_db):
    tenant_repo.insert(
        tenant_id="acme", display_name="Acme Industrial",
        sp_app_id="sp-a", sp_display_name="mt-genie-acme",
    )
    tenant_repo.insert(
        tenant_id="orion", display_name="Orion Travel",
        sp_app_id="sp-o", sp_display_name="mt-genie-orion",
    )

    auth.seed_demo_users()

    # Global operator: no tenant binding.
    op = users_repo.get_by_email("operator@skydesk.app")
    assert op is not None and op.role == "operator" and op.tenant_id is None

    # One bound customer login per tenant.
    acme = users_repo.get_by_email("acme@skydesk.app")
    assert acme is not None and acme.role == "user" and acme.tenant_id == "acme"
    orion = users_repo.get_by_email("orion@skydesk.app")
    assert orion is not None and orion.tenant_id == "orion"

    # Passwords verify against the configured demo password.
    assert auth.verify_password("skydesk", acme.password_hash)


def test_deactivated_tenants_get_no_login(fresh_db):
    tenant_repo.insert(
        tenant_id="acme", display_name="Acme",
        sp_app_id="sp-a", sp_display_name="mt-genie-acme",
    )
    tenant_repo.insert(
        tenant_id="gone", display_name="Gone Co",
        sp_app_id="sp-g", sp_display_name="mt-genie-gone",
    )
    tenant_repo.set_status("gone", "deactivated")

    auth.seed_demo_users()

    assert users_repo.get_by_email("acme@skydesk.app") is not None
    assert users_repo.get_by_email("gone@skydesk.app") is None


def test_seeding_is_idempotent(fresh_db):
    tenant_repo.insert(
        tenant_id="acme", display_name="Acme",
        sp_app_id="sp-a", sp_display_name="mt-genie-acme",
    )
    auth.seed_demo_users()
    auth.seed_demo_users()  # second boot must not duplicate

    assert users_repo.count() == len(users_repo.list_all())
    emails = {u.email for u in users_repo.list_all()}
    assert emails == {
        "operator@skydesk.app",
        "acme@skydesk.app",
        "analyst@skydesk.app",
    }
