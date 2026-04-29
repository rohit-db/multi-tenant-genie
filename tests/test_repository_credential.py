# tests/test_repository_credential.py
import base64
import os
import pytest
import psycopg

from server.lib import db
from server.lib.repository import credential as cred_repo

LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/mtg"


def _can_connect() -> bool:
    try:
        with psycopg.connect(LOCAL_DB, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _can_connect(), reason="Local Postgres not running")


@pytest.fixture
def fresh_db(monkeypatch):
    with psycopg.connect(LOCAL_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", LOCAL_DB)
    db.apply_migrations("sql/lakebase")
    yield


@pytest.fixture
def with_aes_key(monkeypatch):
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("AES_KEY_BASE64", key)
    yield key


@pytest.fixture
def without_aes_key(monkeypatch):
    monkeypatch.delenv("AES_KEY_BASE64", raising=False)
    yield


def test_put_and_get_with_key(fresh_db, with_aes_key):
    cred_repo.put("app-123", "super-secret")
    assert cred_repo.get("app-123") == "super-secret"


def test_put_and_get_without_key_uses_plaintext_marker(fresh_db, without_aes_key):
    cred_repo.put("app-456", "another-secret")
    # Verify it's stored plaintext (with the marker)
    with db.get_connection() as conn:
        raw = conn.execute(
            "SELECT secret_encrypted FROM sp_credentials WHERE sp_app_id = %s",
            ("app-456",),
        ).fetchone()[0]
    assert raw.startswith("plain:")
    assert cred_repo.get("app-456") == "another-secret"


def test_round_trip_ciphertext_is_not_plaintext(fresh_db, with_aes_key):
    cred_repo.put("app-789", "hunter2")
    with db.get_connection() as conn:
        raw = conn.execute(
            "SELECT secret_encrypted FROM sp_credentials WHERE sp_app_id = %s",
            ("app-789",),
        ).fetchone()[0]
    assert "hunter2" not in raw
    assert not raw.startswith("plain:")


def test_get_missing_returns_none(fresh_db, with_aes_key):
    assert cred_repo.get("nope") is None


def test_delete(fresh_db, with_aes_key):
    cred_repo.put("app-x", "secret")
    cred_repo.delete("app-x")
    assert cred_repo.get("app-x") is None


def test_rotate_overwrites(fresh_db, with_aes_key):
    cred_repo.put("app-r", "old")
    cred_repo.put("app-r", "new")  # overwrite
    assert cred_repo.get("app-r") == "new"
