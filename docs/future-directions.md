# Future directions

This page lists deferred hardening and roadmap items referenced elsewhere in the docs. These are directions for the reference implementation, not committed features or guarantees.

- **Edge gateway hardening** — production-grade wildcard-subdomain cookie isolation, TLS termination, and an async token broker in place of the demo synchronous path.
- **Pluggable identity provider** — OIDC SSO (or another IdP) in place of the demo app-session login, so customer-facing auth is delegated rather than app-managed.
- **Per-customer rate limiting and plan enforcement** — tenant-aware throttling and plan/tier quotas enforced at the proxy.
- **SP secret rotation** — a defined rotation cadence and automation for Service Principal OAuth secrets.
- **Full DAB** — extend `databricks.yml` into a complete Declarative Automation Bundle that provisions Lakebase, the secret scope, and environment bindings.
- **Broader test coverage** — auth flow, embed token minting, MCP-vs-REST transport parity, and edge header rewriting.

<a id="multi-genie-space-ui"></a>

## Multi Genie space UI

A localized change list for surfacing a Genie space picker in the Admin tab, enabling per-tenant `genie_space_id` overrides without a redeploy.
