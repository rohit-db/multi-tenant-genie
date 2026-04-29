"""sp_credentials with AES-GCM encryption-at-rest.

Production: ``AES_KEY_BASE64`` env var holds the 32-byte key, urlsafe-base64-encoded.
Local dev: if the env var is absent, secrets are stored with a ``plain:``
prefix and a loud WARN is logged. Production deploy fails closed if the key is
missing (enforced by ``server.lib.config``).
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from server.lib import db

logger = logging.getLogger(__name__)

PLAIN_MARKER = "plain:"


def _key() -> Optional[bytes]:
    raw = os.environ.get("AES_KEY_BASE64")
    if not raw:
        return None
    return base64.urlsafe_b64decode(raw)


def _encrypt(plaintext: str) -> str:
    key = _key()
    if key is None:
        logger.warning(
            "AES_KEY_BASE64 unset — storing SP credential as plaintext "
            "(local-dev only). Set AES_KEY_BASE64 in production."
        )
        return PLAIN_MARKER + plaintext
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode(), associated_data=None)
    return base64.b64encode(nonce + ct).decode()


def _decrypt(value: str) -> str:
    if value.startswith(PLAIN_MARKER):
        return value[len(PLAIN_MARKER):]
    key = _key()
    if key is None:
        raise RuntimeError(
            "Stored credential is encrypted but AES_KEY_BASE64 is unset"
        )
    raw = base64.b64decode(value)
    nonce, ct = raw[:12], raw[12:]
    aes = AESGCM(key)
    return aes.decrypt(nonce, ct, associated_data=None).decode()


def put(sp_app_id: str, secret: str) -> None:
    enc = _encrypt(secret)
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO sp_credentials (sp_app_id, secret_encrypted) "
            "VALUES (%s, %s) "
            "ON CONFLICT (sp_app_id) DO UPDATE "
            "SET secret_encrypted = EXCLUDED.secret_encrypted, "
            "    rotated_at = NOW()",
            (sp_app_id, enc),
        )
        conn.commit()


def get(sp_app_id: str) -> Optional[str]:
    with db.get_connection() as conn:
        cur = conn.execute(
            "SELECT secret_encrypted FROM sp_credentials WHERE sp_app_id = %s",
            (sp_app_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return _decrypt(row[0])


def delete(sp_app_id: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "DELETE FROM sp_credentials WHERE sp_app_id = %s", (sp_app_id,)
        )
        conn.commit()
