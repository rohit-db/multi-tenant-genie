# Local Development

The full local-dev guide lands in Phase 4 of the migration. For now, the short version:

## Prerequisites

- Python 3.11+
- Docker (for the local Postgres that stands in for Lakebase)
- Node 18+ and npm (for the React UI)
- A Databricks workspace profile in `~/.databrickscfg` with admin permission on a target catalog and Genie space

## Quickstart

```bash
./bootstrap.sh           # interactive: writes .env.local, brings up Postgres, applies migrations
./bootstrap.sh --demo    # also seeds three demo tenants and their data
```

Then:

```bash
# Backend
uvicorn server.app:app --reload --port 8000

# Frontend (in another terminal)
cd web && npm install && npm run dev
```

The UI runs on http://localhost:5173 and proxies API calls to http://localhost:8000.

## What lives where

- **Tenants registry & audit log** — local Postgres (named volume `mt-genie-postgres-data`). Stand-in for Lakebase.
- **`sp_tenant_mapping` (the row-filter join)** — UC Delta in your workspace.
- **Bookings / customers (the demo data)** — UC Delta in your workspace.

## Resetting

```bash
docker compose down -v   # nukes the local Postgres data volume
./bootstrap.sh --demo    # rebuild from scratch
```
