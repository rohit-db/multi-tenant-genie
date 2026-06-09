"""Edge / token-broker front door for the multi-tenant Genie app.

This package is a *standalone* service, deliberately decoupled from the
Databricks App in ``server/``. It implements the Firefly-style "edge": it
terminates the public origin, hosts your own login session, and reverse-
proxies authenticated traffic into the Databricks App by injecting an
**edge Service Principal** OAuth token — so external (non-Databricks) users
never see Databricks SSO.

See ``docs/edge-gateway.md`` for the architecture and the local test recipe.
"""
