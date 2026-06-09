# `primitives/` — "Databricks is all you need"

Every module here wraps **one** capability of the Databricks Data Intelligence
Platform behind a small, swappable interface. The services layer
(`server/services/`) composes them into use cases; nothing in this package
knows about HTTP, and (except for the `SPManager` facade) no module here
imports another primitive. Re-skin or re-platform the app by swapping a file
here — the thesis is that you never have to leave Databricks to do it.

## Capability → module map

| Thesis capability | Module | What it wraps |
|---|---|---|
| Per-tenant **identity** (OAuth M2M) | [`identity.py`](identity.py) | Mints/caches `client_credentials` tokens for each tenant SP against `/oidc/v1/token`. |
| Per-tenant **Service Principal** lifecycle | [`service_principals.py`](service_principals.py) | SCIM create/rotate/deactivate/reactivate/delete of the tenant SP + its OAuth secret. |
| **Unity Catalog** governance + isolation | [`unity_catalog.py`](unity_catalog.py) | Data/Genie/dashboard grants, the SQL-warehouse access path, and the row-filter isolation *proof* (`verify_tenant`/`verify_all`). |
| **Genie** Conversation API | [`genie.py`](genie.py) | Natural-language → SQL → rows as the tenant SP (REST transport). |
| **Managed MCP** (Genie) | [`managed_mcp.py`](managed_mcp.py) | Same ask, via the managed MCP server at `/api/2.0/mcp/genie/{space_id}`. |
| **AI/BI** external embedding | [`aibi_embed.py`](aibi_embed.py) | 3-step token exchange that mints a browser-safe embed token for the published dashboard, scoped to the tenant SP. |
| Tenant SP + grants **facade** | [`sp_manager.py`](sp_manager.py) | Composes `service_principals` + `unity_catalog` over one `WorkspaceClient`; the single object the services layer talks to. |

## The one isolation invariant

All transports (REST Genie, Managed MCP, direct SQL, embedded AI/BI) present the
**tenant Service Principal's** OAuth token. Inside the warehouse,
`session_user()` resolves to that SP, so the Unity Catalog row filter joined
against `sp_tenant_mapping` trims every query to that tenant's rows. Isolation
is enforced by UC, not by the proxy or the agent framework — these primitives
only decide *which* identity makes the call.
