"""Edge gateway configuration.

All values come from the environment (loaded from ``edge/.env`` in local
dev — see ``edge/.env.example``). The edge needs three things to do its job:

  1. Where the Databricks App lives          (EDGE_UPSTREAM_URL)
  2. The workspace OIDC endpoint to mint at   (EDGE_WORKSPACE_HOST)
  3. The edge SP credentials                  (EDGE_SP_CLIENT_ID / _SECRET)

Everything else has a sensible default tuned for local http testing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(filepath: str) -> None:
    """Minimal .env loader (mirrors server/app.py) — no extra deps."""
    p = Path(filepath)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


# Load edge-local config before reading the dataclass below. Repo root is the
# parent of this file's parent (edge/ -> repo/).
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_env_file(str(_REPO_ROOT / "edge" / ".env"))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class EdgeConfig:
    # Upstream Databricks App (the thing behind the Apps OAuth proxy).
    upstream_url: str
    # Workspace host that issues OAuth tokens at /oidc/v1/token. The edge SP's
    # token is minted here, not at the app URL.
    workspace_host: str
    # Edge Service Principal — must have CAN_USE on the Databricks App.
    sp_client_id: str
    sp_client_secret: str
    # Where the edge itself listens.
    host: str
    port: int
    # Strip the `Secure` attribute from upstream Set-Cookie headers so the
    # session cookie survives over plain http://localhost during local tests.
    # MUST be False for any real https deployment of the edge.
    rewrite_secure_cookies: bool
    oauth_scope: str

    @property
    def upstream(self) -> str:
        return self.upstream_url.rstrip("/")

    def missing(self) -> list[str]:
        """Required fields that are still blank — for a friendly startup error."""
        required = {
            "EDGE_UPSTREAM_URL": self.upstream_url,
            "EDGE_WORKSPACE_HOST": self.workspace_host,
            "EDGE_SP_CLIENT_ID": self.sp_client_id,
            "EDGE_SP_CLIENT_SECRET": self.sp_client_secret,
        }
        return [k for k, v in required.items() if not v]


CONFIG = EdgeConfig(
    upstream_url=_env("EDGE_UPSTREAM_URL"),
    workspace_host=_env("EDGE_WORKSPACE_HOST") or _env("MT_GENIE_HOST"),
    sp_client_id=_env("EDGE_SP_CLIENT_ID"),
    sp_client_secret=_env("EDGE_SP_CLIENT_SECRET"),
    host=_env("EDGE_HOST", "127.0.0.1"),
    port=int(_env("EDGE_PORT", "9000")),
    rewrite_secure_cookies=_bool("EDGE_REWRITE_SECURE_COOKIES", True),
    oauth_scope=_env("EDGE_OAUTH_SCOPE", "all-apis"),
)
