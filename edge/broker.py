"""Edge token broker.

Mints (and caches) the **edge Service Principal**'s OAuth M2M token. This is
the single token the edge injects on every request it forwards upstream, so
the Databricks Apps OAuth proxy admits the call without showing the end user
Databricks SSO.

We reuse ``server.primitives.identity.TokenMinter`` verbatim — same OAuth
client-credentials exchange, same ~55-minute cache — so the edge and the app
share one, well-tested token path. The edge just pins it to one SP.
"""
from __future__ import annotations

from server.primitives.identity import TokenMinter

from edge.config import CONFIG


class EdgeTokenBroker:
    def __init__(self) -> None:
        # Tokens are minted at the workspace OIDC endpoint, not the app URL.
        self._minter = TokenMinter(host=CONFIG.workspace_host)

    def bearer(self) -> str:
        """Current edge SP access token (minted on first use, then cached)."""
        return self._minter.get_token(CONFIG.sp_client_id, CONFIG.sp_client_secret)

    def invalidate(self) -> None:
        self._minter.invalidate(CONFIG.sp_client_id)


broker = EdgeTokenBroker()
