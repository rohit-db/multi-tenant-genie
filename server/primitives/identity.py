"""Thread-safe per-tenant OAuth M2M token minter.

Given an SP's ``client_id`` / ``client_secret``, exchanges credentials at
the workspace's ``/oidc/v1/token`` endpoint and caches the resulting
access token until ~5 minutes before expiry. One cache entry per SP.

Used by ``genie_client`` to call Genie as the tenant's SP, which is what
lets UC row filters see ``session_user() = <sp_app_id>``.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

from server.lib.config import CONFIG

logger = logging.getLogger(__name__)


class TokenMinter:
    def __init__(self, host: str | None = None):
        self.host = (host or CONFIG.host).rstrip("/")
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get_token(self, client_id: str, client_secret: str) -> str:
        now = time.time()
        with self._lock:
            cached = self._cache.get(client_id)
            if cached and cached[1] - 300 > now:
                return cached[0]

        token, expires_in = self._fetch(client_id, client_secret)
        with self._lock:
            self._cache[client_id] = (token, now + expires_in)
        return token

    def invalidate(self, client_id: str) -> None:
        with self._lock:
            self._cache.pop(client_id, None)

    def _fetch(self, client_id: str, client_secret: str) -> tuple[str, int]:
        logger.info("Minting OAuth token for client_id=%s…", client_id)
        resp = requests.post(
            f"{self.host}/oidc/v1/token",
            data={"grant_type": "client_credentials", "scope": "all-apis"},
            auth=(client_id, client_secret),
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Token exchange failed ({resp.status_code}): {resp.text}"
            )
        body = resp.json()
        return body["access_token"], int(body.get("expires_in", 3600))
