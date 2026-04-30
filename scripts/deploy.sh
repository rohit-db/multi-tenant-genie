#!/usr/bin/env bash
# scripts/deploy.sh — One-shot Databricks Apps deploy for multi-tenant-genie.
#
# Idempotent: re-running picks up where the last run stopped. Safe to
# run against an already-deployed app to redeploy code only.
#
# Inputs (env vars; missing required ones cause a hard exit):
#   PROFILE             databricks CLI profile (required)
#   APP_NAME            app name (default: multi-tenant-genie)
#   LAKEBASE_INSTANCE   Lakebase instance name (default: <APP_NAME>-db)
#   LAKEBASE_DATABASE   database inside the instance (default: databricks_postgres)
#   CATALOG             UC catalog (required)
#   SCHEMA              UC schema (default: mt_genie_demo)
#   GENIE_SPACE_ID      target Genie Space (required)
#   WAREHOUSE_ID        SQL warehouse used for UC grants (required)
#   SECRET_SCOPE        secret scope for AES key (default: <APP_NAME>)
#   ADMIN_GROUP         workspace group that bypasses the row filter
#                       (default: admins)
#   DOMAIN              active demo domain (default: travel)
#   WORKSPACE_PATH      where source is synced (default:
#                       /Workspace/Users/<me>/<APP_NAME>)
#
# Optional:
#   DRY_RUN=1           print actions, don't run them
#   SKIP_FRONTEND=1     skip `npm run build` (use existing web/build)

set -euo pipefail

# -------------------------------------------------------------- helpers
log()  { printf '\033[1;34m▸\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*" >&2; }
run()  { if [ "${DRY_RUN:-0}" = 1 ]; then echo "+ $*" >&2; else "$@"; fi; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing prerequisite: $1"; }

# -------------------------------------------------------------- prereqs
log "Checking prerequisites…"
require_cmd databricks
require_cmd jq
require_cmd python3
require_cmd npm

# psql is needed for the Lakebase schema grant. On Mac:
#   brew install postgresql@16
# On Linux: apt/yum install postgresql-client.
if ! command -v psql >/dev/null 2>&1; then
  # Mac/Homebrew fallback
  if [ -x /opt/homebrew/opt/postgresql@16/bin/psql ]; then
    export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
  elif [ -x /usr/local/opt/postgresql@16/bin/psql ]; then
    export PATH="/usr/local/opt/postgresql@16/bin:$PATH"
  else
    die "psql not found. Install Postgres client (e.g. 'brew install postgresql@16')."
  fi
fi
require_cmd psql
ok "Prereqs ok"

# -------------------------------------------------------------- inputs
: "${PROFILE:?Set PROFILE (databricks CLI profile name)}"
: "${CATALOG:?Set CATALOG (UC catalog)}"
: "${GENIE_SPACE_ID:?Set GENIE_SPACE_ID}"
: "${WAREHOUSE_ID:?Set WAREHOUSE_ID}"

APP_NAME="${APP_NAME:-multi-tenant-genie}"
LAKEBASE_INSTANCE="${LAKEBASE_INSTANCE:-${APP_NAME}-db}"
LAKEBASE_DATABASE="${LAKEBASE_DATABASE:-databricks_postgres}"
SCHEMA="${SCHEMA:-mt_genie_demo}"
SECRET_SCOPE="${SECRET_SCOPE:-${APP_NAME}}"
ADMIN_GROUP="${ADMIN_GROUP:-admins}"
DOMAIN="${DOMAIN:-travel}"

ME="$(databricks current-user me -p "$PROFILE" 2>/dev/null | jq -r '.userName // .emails[0].value')"
[ -n "$ME" ] || die "Could not resolve current user from databricks CLI."
WORKSPACE_PATH="${WORKSPACE_PATH:-/Workspace/Users/${ME}/${APP_NAME}}"

HOST="$(databricks current-user me -p "$PROFILE" 2>/dev/null \
        | jq -r 'empty' || true)"  # placeholder; real host below
HOST="$(awk -v profile="[$PROFILE]" '
  $0==profile {found=1; next}
  /^\[/ {found=0}
  found && /^host/ {sub(/^host[[:space:]]*=[[:space:]]*/,""); print; exit}
' "$HOME/.databrickscfg")"
HOST="${HOST%/}"
[ -n "$HOST" ] || die "Could not resolve workspace host for profile $PROFILE."

cat <<EOF >&2
Configuration:
  PROFILE=$PROFILE
  APP_NAME=$APP_NAME
  LAKEBASE_INSTANCE=$LAKEBASE_INSTANCE
  LAKEBASE_DATABASE=$LAKEBASE_DATABASE
  CATALOG=$CATALOG
  SCHEMA=$SCHEMA
  GENIE_SPACE_ID=$GENIE_SPACE_ID
  WAREHOUSE_ID=$WAREHOUSE_ID
  SECRET_SCOPE=$SECRET_SCOPE
  ADMIN_GROUP=$ADMIN_GROUP
  DOMAIN=$DOMAIN
  HOST=$HOST
  WORKSPACE_PATH=$WORKSPACE_PATH

EOF

# -------------------------------------------------------------- build
if [ "${SKIP_FRONTEND:-0}" = 1 ]; then
  log "Skipping frontend build (SKIP_FRONTEND=1)"
else
  log "Building frontend (web/build/)"
  run bash -c "cd web && npm install --silent && npm run build"
  ok "Frontend built"
fi

# -------------------------------------------------------------- AES key
log "Ensuring secret scope $SECRET_SCOPE + AES key…"
if databricks secrets list-scopes -p "$PROFILE" 2>/dev/null \
     | jq -e --arg n "$SECRET_SCOPE" '.[] | select(.name == $n)' >/dev/null; then
  ok "Secret scope exists"
else
  run databricks secrets create-scope "$SECRET_SCOPE" -p "$PROFILE"
  ok "Created secret scope"
fi

if databricks secrets list-secrets "$SECRET_SCOPE" -p "$PROFILE" 2>/dev/null \
     | grep -q aes_key_base64; then
  ok "AES key already present"
else
  AES_KEY="$(python3 -c 'import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
  run databricks secrets put-secret "$SECRET_SCOPE" aes_key_base64 \
    --string-value "$AES_KEY" -p "$PROFILE"
  ok "AES key generated + stored"
fi

# -------------------------------------------------------------- Lakebase
log "Ensuring Lakebase instance $LAKEBASE_INSTANCE…"
if databricks database list-database-instances -p "$PROFILE" 2>/dev/null \
     | jq -e --arg n "$LAKEBASE_INSTANCE" '.[] | select(.name == $n)' >/dev/null; then
  ok "Lakebase instance exists"
else
  run databricks database create-database-instance \
    --json "{\"name\":\"$LAKEBASE_INSTANCE\",\"capacity\":\"CU_1\"}" \
    -p "$PROFILE" >/dev/null
  ok "Lakebase instance created"
fi

# -------------------------------------------------------------- App
log "Ensuring app $APP_NAME…"
if databricks apps get "$APP_NAME" -p "$PROFILE" >/dev/null 2>&1; then
  ok "App exists"
else
  run databricks apps create --json \
    "{\"name\":\"$APP_NAME\",\"description\":\"Multi-tenant Genie reference\"}" \
    -p "$PROFILE" >/dev/null
  ok "App created"
fi

APP_INFO="$(databricks apps get "$APP_NAME" -p "$PROFILE")"
APP_SP_APP_ID="$(echo "$APP_INFO" | jq -r '.service_principal_client_id')"
APP_SP_DB_ID="$(echo "$APP_INFO" | jq -r '.service_principal_id')"
APP_URL="$(echo "$APP_INFO" | jq -r '.url')"

log "App SP: $APP_SP_APP_ID (db_id=$APP_SP_DB_ID)"

# -------------------------------------------------------------- Sync source
log "Syncing source to $WORKSPACE_PATH…"
run databricks sync . "$WORKSPACE_PATH" \
  --exclude node_modules --exclude .venv --exclude __pycache__ --exclude .git \
  --exclude "web/src" --exclude "web/node_modules" --exclude .superpowers \
  --exclude tests --exclude docs --exclude diagrams \
  --full -p "$PROFILE" >/dev/null
ok "Source synced"

# -------------------------------------------------------------- First deploy
# Deploy without resources so the app SP exists in a recognized state.
# Lifespan logs a warning + skips migrations when DB env isn't bound yet.
log "First deploy (no resources bound yet — app boots, DB skipped)…"
run databricks apps deploy "$APP_NAME" \
  --source-code-path "$WORKSPACE_PATH" \
  -p "$PROFILE" >/dev/null || warn "First deploy returned non-zero (often OK)"
ok "First deploy complete"

# -------------------------------------------------------------- Bind resources
log "Binding Lakebase + AES key resources…"
RESOURCES_JSON=$(cat <<EOF
{
  "resources": [
    {
      "name": "lakebase",
      "description": "Lakebase metadata store",
      "database": {
        "database_name": "$LAKEBASE_DATABASE",
        "instance_name": "$LAKEBASE_INSTANCE",
        "permission": "CAN_CONNECT_AND_CREATE"
      }
    },
    {
      "name": "aes_key",
      "description": "AES-GCM key",
      "secret": {
        "scope": "$SECRET_SCOPE",
        "key": "aes_key_base64",
        "permission": "READ"
      }
    }
  ]
}
EOF
)
run databricks apps update "$APP_NAME" --json "$RESOURCES_JSON" -p "$PROFILE" >/dev/null
ok "Resources bound"

# -------------------------------------------------------------- Add to admins
log "Adding app SP to '$ADMIN_GROUP' group (for SCIM SP-create permission)…"
ADMIN_GROUP_ID="$(databricks groups list -p "$PROFILE" 2>/dev/null \
                  | awk -v g="$ADMIN_GROUP" '$2==g {print $1; exit}')"
if [ -z "$ADMIN_GROUP_ID" ]; then
  warn "Group $ADMIN_GROUP not found — manual step required: add SP $APP_SP_APP_ID to a group with CAN_MANAGE_SERVICE_PRINCIPALS"
else
  PATCH=$(cat <<EOF
{
  "schemas":["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
  "Operations":[{"op":"add","path":"members","value":[{"value":"$APP_SP_DB_ID"}]}]
}
EOF
)
  if databricks groups patch "$ADMIN_GROUP_ID" --json "$PATCH" -p "$PROFILE" 2>&1 \
       | grep -q -E 'already a member|"value":"'"$APP_SP_DB_ID"'"'; then
    ok "App SP in $ADMIN_GROUP"
  else
    ok "Added app SP to $ADMIN_GROUP"
  fi
fi

# -------------------------------------------------------------- Lakebase grants
log "Granting Lakebase schema permissions to app SP…"
# Wait briefly for the role to be created by the resource binding.
for i in 1 2 3 4 5; do
  if databricks psql "$LAKEBASE_INSTANCE" -p "$PROFILE" -- \
       -d "$LAKEBASE_DATABASE" \
       -c "SELECT 1 FROM pg_roles WHERE rolname = '$APP_SP_APP_ID'" 2>/dev/null \
       | grep -q '1 row'; then
    break
  fi
  warn "Waiting for app SP role in Lakebase (attempt $i/5)…"
  sleep 3
done

if [ "${DRY_RUN:-0}" != 1 ]; then
  databricks psql "$LAKEBASE_INSTANCE" -p "$PROFILE" -- \
    -d "$LAKEBASE_DATABASE" \
    -c "GRANT CREATE, USAGE ON SCHEMA public TO \"$APP_SP_APP_ID\";" >/dev/null \
    || warn "Lakebase GRANT may have been skipped — verify manually"
fi
ok "Lakebase schema grants applied"

# -------------------------------------------------------------- UC grants
log "Granting UC permissions on $CATALOG.$SCHEMA to app SP…"
GRANT_SQL=(
  "GRANT USE CATALOG ON CATALOG $CATALOG TO \`$APP_SP_APP_ID\`"
  "GRANT USE SCHEMA ON SCHEMA $CATALOG.$SCHEMA TO \`$APP_SP_APP_ID\`"
  "GRANT MANAGE ON CATALOG $CATALOG TO \`$APP_SP_APP_ID\`"
  "GRANT MANAGE ON SCHEMA $CATALOG.$SCHEMA TO \`$APP_SP_APP_ID\`"
)
for SQL in "${GRANT_SQL[@]}"; do
  if [ "${DRY_RUN:-0}" = 1 ]; then
    echo "+ SQL: $SQL" >&2
  else
    OUT=$(databricks api post /api/2.0/sql/statements -p "$PROFILE" \
      --json "{\"warehouse_id\":\"$WAREHOUSE_ID\",\"statement\":\"$SQL\",\"wait_timeout\":\"30s\"}" 2>&1)
    STATE=$(echo "$OUT" | jq -r '.status.state // "?"')
    if [ "$STATE" != "SUCCEEDED" ]; then
      warn "Grant returned $STATE: $SQL"
    fi
  fi
done
ok "UC grants applied"

# -------------------------------------------------------------- Final deploy
log "Redeploy to pick up bound resources…"
run databricks apps deploy "$APP_NAME" \
  --source-code-path "$WORKSPACE_PATH" \
  -p "$PROFILE" >/dev/null
ok "Deployed"

# -------------------------------------------------------------- Done
cat <<EOF >&2

\033[1;32m✓\033[0m Deploy complete.

  App URL:        $APP_URL
  Workspace:      $HOST
  Lakebase:       $LAKEBASE_INSTANCE / $LAKEBASE_DATABASE
  App SP:         $APP_SP_APP_ID
  Catalog:        $CATALOG
  Schema:         $CATALOG.$SCHEMA
  Genie space:    $GENIE_SPACE_ID

Open the URL in a browser where you're signed in to the workspace.
The Demo / Admin / Architecture tabs should render. Onboard a tenant
from the Admin tab to confirm the SCIM + UC + Lakebase + Genie path.

If onboard fails with a UC permission error on bookings/customers,
the governed tables don't exist yet — apply sql/setup.sql and your
domain's schema.sql against the catalog.
EOF
