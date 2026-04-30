# Deploying as a Databricks App

This is the canonical production deploy. The Apps platform handles the Lakebase, the warehouse permission, the Genie space permission, and the AES key — `app.yaml` declares them; the deploy command provisions and binds them.

## Prerequisites

- Databricks workspace with Apps enabled.
- Permission to create Lakebase databases (`CAN_USE` on the workspace's database catalog).
- A SQL warehouse you can grant `CAN_USE` on — Genie + the proxy use it.
- A Genie Space the app will run questions against. The app's own SP needs `CAN_RUN` on it.
- Your local Databricks CLI authenticated against the target workspace (`databricks auth login`).

## Step 1 — Create the AES key secret

The proxy encrypts each tenant's OAuth secret at rest with AES-GCM. The 32-byte key lives in a Databricks Secret. **In production deploys, the proxy refuses to start without it.**

```bash
# Generate a fresh 32-byte urlsafe-base64 key
python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

# Create the scope + write the key
databricks secrets create-scope multi-tenant-genie
databricks secrets put-secret multi-tenant-genie aes_key_base64
# (the CLI prompts for the value — paste the urlsafe-b64 string from above)
```

## Step 2 — Grant the app's SP `CAN_MANAGE_SERVICE_PRINCIPALS`

The app onboards tenants by creating Service Principals via the workspace SCIM API. The Databricks-Apps-issued SP needs workspace-level permission for that.

After deploying once (Step 4) the App's SP exists. Grant it:

```bash
# Workspace admin role grants the equivalent permission. This is the
# simplest path for a reference deploy. For production, scope the
# permission to just CAN_MANAGE_SERVICE_PRINCIPALS via the workspace
# admin console.
APP_SP_ID=$(databricks apps get multi-tenant-genie --output json | jq -r '.app_status.service_principal_client_id')
databricks workspace-conf set-status \
  "{\"users\": {\"workspace_users.add\": [\"${APP_SP_ID}\"]}}"
```

(The exact API for SP role grants varies by workspace setup. The simplest pre-production approach: add the App SP to the `admins` group via the account console.)

## Step 3 — Set the deploy variables

`app.yaml` references variables (`${var.host}`, `${var.catalog}`, etc.) that the deploy command resolves.

Create `app-vars.yaml`:

```yaml
host: https://your-workspace.cloud.databricks.com
catalog: your_catalog
schema: mt_genie
warehouse_id: 0123abc456def789
genie_space_id: 0123456789abcdef0123456789abcdef
admin_group: admins
secret_scope: multi-tenant-genie
domain: travel
```

## Step 4 — Create + deploy

```bash
databricks apps create multi-tenant-genie

databricks apps deploy multi-tenant-genie \
  --source-code-path . \
  --vars app-vars.yaml
```

The first deploy provisions the Lakebase instance — that takes a few minutes. Subsequent deploys reuse it.

## Step 5 — Verify the app is healthy

```bash
APP_URL=$(databricks apps get multi-tenant-genie --output json | jq -r '.url')
curl -sf "${APP_URL}/health"
```

Expected: `{"status":"healthy"}`.

Then open `${APP_URL}` in a browser. The Demo / Admin / Architecture tabs should render. Onboard a tenant from the Admin tab — that exercises the SCIM API, Lakebase, and UC mapping in one click.

## Troubleshooting

**App fails to start with `AES_KEY_BASE64 unset`:** the secret didn't bind. Re-check Step 1, confirm the secret scope name matches the `secret_scope` variable in `app-vars.yaml`.

**Onboard fails with 403 / "permission denied":** the App SP doesn't have `CAN_MANAGE_SERVICE_PRINCIPALS`. Re-check Step 2.

**Lakebase migrations fail on first deploy:** check the app logs (`databricks apps logs multi-tenant-genie`). Usually a missing `CAN_USE` on the database catalog. The Lakebase resource declaration in `app.yaml` requests it; sometimes the workspace admin needs to approve the request.

**Genie returns 404 for tenant queries:** the Genie space exists but the App SP doesn't have `CAN_RUN`. Grant via the Genie Space → Permissions UI, or wait for the deploy's `genie_space` resource binding to apply.

## Migrating from local dev to Apps

The data model is identical. To move local-dev state to a deployed app:

1. `pg_dump` your local Postgres `client_registry` + `sp_credentials` + `audit_log`.
2. `databricks apps logs --follow` until the app boots.
3. `pg_restore` into the Apps Lakebase database.

For most reference users this is unnecessary — re-onboard the demo tenants in the deployed app via the Admin tab.
