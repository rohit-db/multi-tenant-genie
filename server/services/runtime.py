"""Process-wide singletons and shared accessors for the service layer.

One ``SPManager`` and one ``TokenMinter`` per process, plus a credential
lookup helper. Centralizing them here is what lets the services stay
decoupled from the routers: previously ``genie`` and ``tenants`` imported
each other (genie used ``tenants._mgr()``; tenants late-imported
``genie._minter``). Both now resolve everything through this module, so the
dependency arrows only ever point routers -> services -> primitives.
"""
from __future__ import annotations

from typing import Optional

from server.primitives.identity import TokenMinter
from server.primitives.sp_manager import SPManager

_mgr_singleton: Optional[SPManager] = None
_minter_singleton: Optional[TokenMinter] = None


def manager() -> SPManager:
    """The shared SP lifecycle + grants manager (lazy singleton)."""
    global _mgr_singleton
    if _mgr_singleton is None:
        _mgr_singleton = SPManager()
    return _mgr_singleton


def minter() -> TokenMinter:
    """The shared OAuth M2M token minter (lazy singleton, cache-aware)."""
    global _minter_singleton
    if _minter_singleton is None:
        _minter_singleton = TokenMinter()
    return _minter_singleton


def invalidate_minter(sp_app_id: str) -> None:
    """Drop any cached token for an SP (used on rotate/deactivate/delete)."""
    if not sp_app_id:
        return
    try:
        minter().invalidate(sp_app_id)
    except Exception:
        pass


def secret_for_sp(sp_app_id: str) -> Optional[str]:
    """Decrypted client secret for an SP from the Lakebase credential store."""
    from server.lib.repository import credential as cred_repo

    return cred_repo.get(sp_app_id)
