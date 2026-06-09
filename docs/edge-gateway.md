# Edge / Token-Broker Front Door

This is the optional **external front door** for the app — the piece that lets
customer-facing users reach the product **without ever seeing Databricks SSO**.
It is modeled directly on the [Firefly Analytics](https://www.firefly-analytics.com/docs/architecture/overview)
SSO-SPN pattern (Next.js front end + a proxy that holds Databricks OAuth and
brokers requests into the Databricks App). Credit to the Firefly maintainers in
`#partner-architecture`.

> TL;DR — the Databricks App can't be made public; it always sits behind the
> Apps OAuth proxy. The edge is a thin reverse proxy you host yourself that
> presents an **edge Service Principal** OAuth token to clear that proxy, while
> your own login (the app's `mtg_session` cookie) decides *who the user is*.

## Why it exists

A Databricks App is always protected by the Apps OAuth proxy. That's great for
internal/SSO users, but an OEM/embedded product needs to onboard *external*
customers who don't have Databricks accounts and shouldn't see Databricks
login. The fix is the same one Firefly uses: keep auth and the public origin
**outside** Databricks, and broker into the app server-side.

```
                                        edge SP OAuth bearer
                                       (clears Apps OAuth proxy)
 Browser ──http──▶ Edge gateway ──https──────────────────────▶ Databricks App
 (your origin)     (edge/, :9000)   + passes mtg_session cookie   (server/, behind
                   your login                                      the OAuth proxy)
                                                                        │
                                                       per-tenant SP ───┘ (Genie / SQL,
                                                       UC row filter      unchanged)
```

Two credentials, two jobs:

| Credential | Who sets it | Job |
|---|---|---|
| **Edge SP OAuth token** | the edge (`edge/broker.py`) | clears the **Apps OAuth proxy** (the front door) |
| **`mtg_session` cookie** | the app's `/api/auth/login` | identifies the **end user → tenant** (rides through the edge unchanged) |
| **Per-tenant SP token** | the app (`genie_service`) | runs Genie/SQL as the tenant; **UC row filter** isolates data |

The edge changes *nothing* about data isolation — the per-tenant SP path in the
app is untouched. It only changes *how the browser reaches the app*.

## Layout

```
edge/
  config.py    # EdgeConfig from env (edge/.env)
  broker.py    # mints + caches the edge SP token (reuses server TokenMinter)
  proxy.py     # transparent reverse proxy: bearer injection, cookie/Location rewrite
  app.py       # FastAPI edge app (catch-all proxy + /__edge/health)
  run.sh       # local runner
  .env.example # copy to edge/.env
```

The edge imports `server.primitives.identity.TokenMinter` so the edge and the
app share one OAuth token path. It deliberately does **not** import the rest of
the app — it's a separate process you could deploy anywhere (Vercel, a VM, a
container) in front of the Databricks App.

## Prerequisites

1. A deployed Databricks App (see [deploy.md](deploy.md)). Get its URL:
   ```bash
   databricks apps get multi-tenant-genie -p <profile> | jq -r .url
   ```
2. An **edge Service Principal** with **CAN_USE** on that app. Create an SP +
   OAuth secret in the workspace, then grant it CAN_USE on the app (Apps UI →
   Permissions, or the permissions API). Keep its `client_id` + `client_secret`.

## Local test recipe

```bash
# 1) Configure
cp edge/.env.example edge/.env
#   set EDGE_UPSTREAM_URL, EDGE_WORKSPACE_HOST, EDGE_SP_CLIENT_ID/SECRET

# 2) Prove the SP token clears the Apps OAuth proxy (the one real unknown)
set -a; source edge/.env; set +a
python scripts/edge_smoke.py
#   expect: "with bearer -> ok ... The edge SP token CLEARS the Apps OAuth proxy."

# 3) Run the edge and use the product through it
./edge/run.sh                      # http://127.0.0.1:9000
open http://127.0.0.1:9000
#   log in as a seeded customer login (e.g. analyst@skydesk.app / skydesk)
#   -> Home / Ask / Dashboards all work, scoped to that tenant's SP.
```

Check edge readiness any time:

```bash
curl -s localhost:9000/__edge/health | jq .
```

## What the test proves

- **Front door**: the browser only ever talks to `localhost:9000`. It never
  sees `*.cloud.databricks.com` or Databricks SSO.
- **SP hop**: the edge SP OAuth token is accepted by the Apps OAuth proxy
  (a workspace PAT is *not* — that's why `edge_smoke.py` exists).
- **Identity + isolation intact**: login still sets `mtg_session`; asking a
  question still resolves tenant → mints the **tenant** SP token → Genie answer
  is trimmed by the UC row filter. The edge is transparent to all of it.

## Going to production

- Terminate **https** at the edge and set `EDGE_REWRITE_SECURE_COOKIES=0` so the
  `Secure` cookie attribute is preserved.
- Put your real customer login / IdP in front of (or inside) the edge. The app's
  `mtg_session` remains the bridge; you can also federate external identities
  into the Databricks account via SCIM if you later want per-user (vs per-SP)
  attribution.
- Rotate the edge SP secret like any other credential; the broker re-mints on
  expiry automatically.

## Limitations

- HTTP request/response proxying only (no WebSocket upgrade) — the app doesn't
  need WebSockets today.
- AI/BI dashboard embedding talks to Databricks directly from the browser using
  its own short-lived embed token; that path is independent of the edge.
