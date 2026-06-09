# Local Development

This is the secondary deploy path — the canonical deploy is as a Databricks App ([docs/deploy.md](deploy.md)). Local dev is what you use to iterate on the proxy or UI without a deploy roundtrip.

## Prerequisites

- Python 3.11 or newer
- Docker (for the local Postgres that stands in for Lakebase)
- Node 18+ and npm (for the React UI)
- A Databricks workspace profile in `~/.databrickscfg` with permission to create Service Principals + read your target catalog
- A target Genie Space with the SPs you'll create granted `CAN_RUN`

## One-shot setup

```bash
./bootstrap.sh           # interactive — writes .env.local, brings up Postgres, applies migrations
./bootstrap.sh --demo    # the above + seeds three demo tenants in your workspace
```

The script prompts for:
- Databricks workspace host (e.g. `https://abc.cloud.databricks.com`)
- Databricks profile name from `~/.databrickscfg`
- UC catalog
- UC schema (default `mt_genie_demo`)
- Genie space ID

It writes `.env.local` and exits.

## Running the app

Two terminals:

```bash
# Terminal 1 — backend
uvicorn server.app:app --reload --port 8000

# Terminal 2 — frontend (Vite dev server, proxies /api → :8000)
cd web && npm install && npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## Optional: the external front door (edge gateway)

To exercise the Firefly-style external login flow — where customer-facing users
reach the product **without** Databricks SSO — run the edge / token-broker in
front of the **deployed** app. It hosts your origin, keeps the app session
cookie, and brokers into the Databricks App using an edge Service Principal
token. See [edge-gateway.md](edge-gateway.md) for the full recipe; the short
version:

```bash
cp edge/.env.example edge/.env     # set upstream URL + edge SP creds
set -a; source edge/.env; set +a
python scripts/edge_smoke.py       # prove the SP token clears the Apps proxy
./edge/run.sh                      # http://127.0.0.1:9000
```

## What lives where

| Data | Store |
|---|---|
| `client_registry`, `sp_credentials`, `audit_log` | Local Postgres (Docker volume `mt-genie-postgres-data`) — stand-in for Lakebase. |
| `sp_tenant_mapping` | UC Delta in your workspace — the row filter joins this. |
| `bookings`, `customers` (demo data) | UC Delta in your workspace. |
| Active domain pack | `domain/<name>/` — selects via `DOMAIN` env var. |

## AES key in local dev

By default `AES_KEY_BASE64` is **unset** locally and SP credentials are stored with a `plain:` prefix. The proxy logs a warning. This is acceptable for throwaway demo data; for anything closer to production, set the key:

```bash
export AES_KEY_BASE64=$(python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
echo "AES_KEY_BASE64=$AES_KEY_BASE64" >> .env.local
```

## Running the tests

```bash
pytest tests/                                  # full suite (requires Postgres up)
pytest tests/test_smoke.py                     # fast sanity check, no Postgres
pytest tests/ -k "not test_repository"         # skip the Lakebase-backed tests
```

57 tests total. The 21 Lakebase-backed tests skip cleanly if Postgres isn't reachable.

## Resetting

```bash
docker compose down -v       # nukes the Lakebase data volume
./bootstrap.sh --demo        # rebuild from scratch
```

## Common issues

**`DATABASE_URL is not set`** when running uvicorn: source `.env.local` first (`set -a; source .env.local; set +a`).

**Ports 5173 / 8000 in use**: `lsof -ti:5173 | xargs kill` (or :8000).

**`SP {sp_app_id} not found`** when asking a question: the workspace deleted the SP behind the proxy's back. Deactivate then re-onboard the tenant from the Admin tab.

**Genie returns "no permission"**: the SP needs `CAN_RUN` on the Genie space. The proxy attempts `grant_genie_access` on every onboard, but if your account-level role doesn't allow that PATCH, you'll need a workspace admin to grant manually.
