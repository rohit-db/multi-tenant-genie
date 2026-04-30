# Deploying as a Databricks App

The canonical production deploy. The fastest path is a single command: `scripts/deploy.sh`. The full step-by-step is below for anyone who wants to understand or debug the flow.

## Prerequisites

- Databricks workspace with Apps enabled. **Serverless workspace required** for Lakebase.
- Permission to create Lakebase database instances (`databricks database create-database-instance`).
- A SQL warehouse you can grant `CAN_USE` on — Genie + the proxy use it.
- A Genie Space the app will run questions against.
- Local tooling:
  - `databricks` CLI (≥ 0.297) authenticated against the target workspace
  - `psql` client (`brew install postgresql@16` on Mac)
  - `jq`
  - `python3`
  - `npm` and Node ≥ 18

## Quickstart — one command

```bash
PROFILE=my-workspace-profile \
CATALOG=my_catalog \
GENIE_SPACE_ID=0123456789abcdef0123456789abcdef \
WAREHOUSE_ID=abc123def456 \
./scripts/deploy.sh
```

That's it. The script does:

1. Build the frontend (`web/build/`).
2. Generate a 32-byte AES key, store in a Databricks Secret scope.
3. Create a Lakebase instance (default name: `<APP_NAME>-db`).
4. Create the app (default name: `multi-tenant-genie`).
5. Sync source to `/Workspace/Users/<you>/<APP_NAME>`.
6. First deploy (the app boots even without DB resources — lifespan logs a warning and skips migrations).
7. Bind the Lakebase + AES key resources via `databricks apps update`.
8. Add the app SP to the `admins` group (for SCIM SP-create permission).
9. Grant the app SP `CREATE, USAGE ON SCHEMA public` in Lakebase (so migrations can run).
10. Grant the app SP UC permissions on the catalog/schema.
11. Final deploy with all bindings in place.
12. Print the app URL.

Re-running the script is idempotent — every step skips if it's already done.

## What you can override

| Env var | Default | Purpose |
|---|---|---|
| `PROFILE` | *required* | Databricks CLI profile |
| `APP_NAME` | `multi-tenant-genie` | Apps name |
| `LAKEBASE_INSTANCE` | `<APP_NAME>-db` | Lakebase instance name |
| `LAKEBASE_DATABASE` | `databricks_postgres` | Database name inside the instance |
| `CATALOG` | *required* | UC catalog |
| `SCHEMA` | `mt_genie_demo` | UC schema |
| `GENIE_SPACE_ID` | *required* | Target Genie Space |
| `WAREHOUSE_ID` | *required* | SQL warehouse used for UC grants |
| `SECRET_SCOPE` | `<APP_NAME>` | Secret scope for the AES key |
| `ADMIN_GROUP` | `admins` | Workspace group that bypasses the row filter |
| `DOMAIN` | `travel` | Active demo domain pack |
| `DRY_RUN` | `0` | Set to `1` to print actions without running |
| `SKIP_FRONTEND` | `0` | Set to `1` to reuse existing `web/build/` |

## Step-by-step (manual)

If you want to run the steps yourself or debug a partial deploy:

### 1. Build the frontend

```bash
cd web && npm install && npm run build && cd ..
```

`web/build/` is what Apps serves as the static SPA. **Note:** the global `.gitignore` would otherwise exclude it — `web/build/` is explicitly un-ignored so `databricks sync` uploads it.

### 2. Create the AES key secret

```bash
databricks secrets create-scope multi-tenant-genie -p "$PROFILE"
KEY=$(python3 -c 'import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
databricks secrets put-secret multi-tenant-genie aes_key_base64 --string-value "$KEY" -p "$PROFILE"
```

### 3. Create the Lakebase instance

```bash
databricks database create-database-instance \
  --json '{"name":"multi-tenant-genie-db","capacity":"CU_1"}' \
  -p "$PROFILE"
```

Returns immediately; the instance reaches `AVAILABLE` within a few seconds.

### 4. Create the app

```bash
databricks apps create \
  --json '{"name":"multi-tenant-genie","description":"Multi-tenant Genie reference"}' \
  -p "$PROFILE"
```

The response carries the app's auto-issued Service Principal client ID — capture it; you'll need it for grants:

```bash
APP_SP_APP_ID=$(databricks apps get multi-tenant-genie -p "$PROFILE" \
  | jq -r '.service_principal_client_id')
APP_SP_DB_ID=$(databricks apps get multi-tenant-genie -p "$PROFILE" \
  | jq -r '.service_principal_id')
```

### 5. Sync source

```bash
databricks sync . /Workspace/Users/your.email@company.com/multi-tenant-genie \
  --exclude node_modules --exclude .venv --exclude __pycache__ --exclude .git \
  --exclude "web/src" --exclude "web/node_modules" --exclude .superpowers \
  --exclude tests --exclude docs --exclude diagrams \
  --full \
  -p "$PROFILE"
```

### 6. First deploy

```bash
databricks apps deploy multi-tenant-genie \
  --source-code-path /Workspace/Users/your.email@company.com/multi-tenant-genie \
  -p "$PROFILE"
```

The app starts with a warning about missing `PGHOST`/`DATABASE_URL` — that's expected; we bind resources next.

### 7. Bind resources

```bash
databricks apps update multi-tenant-genie --json '{
  "resources": [
    {
      "name": "lakebase",
      "description": "Lakebase metadata store",
      "database": {
        "database_name": "databricks_postgres",
        "instance_name": "multi-tenant-genie-db",
        "permission": "CAN_CONNECT_AND_CREATE"
      }
    },
    {
      "name": "aes_key",
      "description": "AES-GCM key",
      "secret": {
        "scope": "multi-tenant-genie",
        "key": "aes_key_base64",
        "permission": "READ"
      }
    }
  ]
}' -p "$PROFILE"
```

This registers a Lakebase Postgres role for the app SP automatically.

### 8. Add the app SP to `admins`

The proxy creates Service Principals for each tenant via the SCIM API. That endpoint requires admin permission.

```bash
ADMIN_GROUP_ID=$(databricks groups list -p "$PROFILE" \
  | awk '$2=="admins" {print $1}')

databricks groups patch "$ADMIN_GROUP_ID" --json "{
  \"schemas\":[\"urn:ietf:params:scim:api:messages:2.0:PatchOp\"],
  \"Operations\":[{\"op\":\"add\",\"path\":\"members\",\"value\":[{\"value\":\"$APP_SP_DB_ID\"}]}]
}" -p "$PROFILE"
```

For production, scope this more tightly — `CAN_MANAGE_SERVICE_PRINCIPALS` is sufficient and avoids granting full admin.

### 9. Grant Lakebase schema permissions

Apps creates a Postgres role for the app SP when the database resource is bound. That role can connect but cannot `CREATE TABLE` in `public` until granted:

```bash
databricks psql multi-tenant-genie-db -p "$PROFILE" -- \
  -d databricks_postgres \
  -c "GRANT CREATE, USAGE ON SCHEMA public TO \"$APP_SP_APP_ID\";"
```

Without this, the migration runner fails on the first `CREATE TABLE` and the proxy's lifespan logs an error.

### 10. Grant UC permissions

The app SP needs to read tenant data, write the mapping table, and grant new tenant SPs access:

```bash
WAREHOUSE_ID=...

for SQL in \
  "GRANT USE CATALOG ON CATALOG $CATALOG TO \`$APP_SP_APP_ID\`" \
  "GRANT USE SCHEMA ON SCHEMA $CATALOG.$SCHEMA TO \`$APP_SP_APP_ID\`" \
  "GRANT MANAGE ON CATALOG $CATALOG TO \`$APP_SP_APP_ID\`" \
  "GRANT MANAGE ON SCHEMA $CATALOG.$SCHEMA TO \`$APP_SP_APP_ID\`"
do
  databricks api post /api/2.0/sql/statements -p "$PROFILE" --json \
    "{\"warehouse_id\":\"$WAREHOUSE_ID\",\"statement\":\"$SQL\",\"wait_timeout\":\"30s\"}"
done
```

`MANAGE` on the catalog is needed because the proxy issues per-tenant grants on data tables when each tenant onboards.

### 11. Final deploy

```bash
databricks apps deploy multi-tenant-genie \
  --source-code-path /Workspace/Users/your.email@company.com/multi-tenant-genie \
  -p "$PROFILE"
```

This time the app boots, applies Lakebase migrations (creating `client_registry`, `sp_credentials`, `audit_log`, `token_cache`, `schema_migrations`), and serves the React UI from `web/build/`.

## Verifying

Open the app URL in a browser where you're signed in to the workspace:

```bash
databricks apps get multi-tenant-genie -p "$PROFILE" | jq -r '.url'
```

You should see the Demo / Admin / Architecture tabs. From the Admin tab, click "Onboard one" — the request goes through the SCIM API, Lakebase, and UC mapping in ~1 second.

If onboard fails with `permission denied for sp_tenant_mapping`, the UC schema tables don't exist yet. Apply `sql/setup.sql` and your domain's `domain/<name>/schema.sql` against the catalog/schema (paste into the workspace SQL editor or run via `databricks api post /api/2.0/sql/statements`).

## Troubleshooting

**App fails to start with `permission denied for schema public`** — Step 9 was skipped or failed. Re-run the `databricks psql … GRANT CREATE, USAGE ON SCHEMA public` command.

**Onboard returns 403 `is only accessible by admins`** — Step 8 was skipped, OR the SCIM permission propagation hasn't reached the proxy SP yet (can take 30s). Wait and retry.

**Onboard returns `User does not have USE CATALOG` / `MANAGE`** — Step 10 was skipped or used a different catalog. Re-run the UC grants against your actual catalog.

**Onboard returns `User does not have CAN_RUN on Genie space`** — the App SP's admin-group membership should cover this; if you scoped to `CAN_MANAGE_SERVICE_PRINCIPALS` only, also grant the SP `CAN_RUN` on the Genie Space via the Genie UI.

**Inspector shows DNS errors connecting to Lakebase** — the `valueFrom: lakebase` env vars in `app.yaml` got rewritten incorrectly. The current `app.yaml` does not enumerate PG* env vars; Apps auto-injects them. If you've edited the file, make sure no `valueFrom: lakebase` block remains.

**`databricks sync` skipped `web/build/`** — the global `.gitignore` matches `build/`. `.gitignore` has an explicit `!web/build/` negation; if you've edited the gitignore, restore the negation.

## Production hardening

This is a reference deploy. Before running in front of real customer traffic, consider:

- Replace the admins-group membership with a tightly-scoped `CAN_MANAGE_SERVICE_PRINCIPALS` grant.
- Cache the OAuth token used for Lakebase auth (currently minted per request — fine for low load).
- Move the in-process bulk onboard runner to a Databricks Job (see [docs/future-directions.md](future-directions.md)).
- Enable Lakebase Synced Tables to mirror `audit_log` to UC for analytics.
- Set up rate limits per tenant via `client_registry.rate_limit_per_min`.
