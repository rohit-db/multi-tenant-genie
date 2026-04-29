#!/usr/bin/env bash
# bootstrap.sh — one-shot local-dev setup for multi-tenant-genie.
#
# Usage:
#   ./bootstrap.sh           # set up env, bring up Postgres, install deps
#   ./bootstrap.sh --demo    # the above + seed three demo tenants in your workspace
set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE=".env.local"

if [ ! -f "$ENV_FILE" ]; then
    echo "Creating $ENV_FILE — answer a few questions:"
    read -rp "Databricks workspace host (e.g. https://abc.cloud.databricks.com): " HOST
    read -rp "Databricks profile name (from ~/.databrickscfg): " PROFILE
    read -rp "UC catalog: " CATALOG
    read -rp "UC schema (default: mt_genie): " SCHEMA
    SCHEMA="${SCHEMA:-mt_genie}"
    read -rp "Genie space ID: " GENIE
    cat > "$ENV_FILE" <<EOF
MT_GENIE_HOST=$HOST
MT_GENIE_PROFILE=$PROFILE
MT_GENIE_CATALOG=$CATALOG
MT_GENIE_SCHEMA=$SCHEMA
MT_GENIE_SPACE_ID=$GENIE
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mtg
DOMAIN=travel
EOF
    echo "Wrote $ENV_FILE."
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

echo "→ Bringing up local Postgres (docker-compose)…"
docker compose up -d

echo "→ Waiting for Postgres to accept connections…"
until docker compose exec -T postgres pg_isready -U postgres -d mtg >/dev/null 2>&1; do
    sleep 1
done

echo "→ Installing Python deps…"
pip install -e ".[dev]" >/dev/null

echo "→ Applying Lakebase migrations…"
python -c "from server.lib import db; db.apply_migrations('sql/lakebase')"

if [ "${1:-}" = "--demo" ]; then
    echo "→ Seeding demo tenants in workspace ${MT_GENIE_HOST}…"
    python scripts/seed_demo.py
fi

echo
echo "Done. To run the app:"
echo "  uvicorn server.app:app --reload --port 8000"
echo "And in another terminal:"
echo "  cd web && npm install && npm run dev"
