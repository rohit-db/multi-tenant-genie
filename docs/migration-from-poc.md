# Migrating from the POC

The original repo was a working POC for one specific account. This page is for anyone who cloned that version and wants to move to the generalized reference.

## What changed

| Layer | Before | After |
|---|---|---|
| Top-level layout | `api/`, `src/lib/`, `src/scripts/`, `src/sql/` | `server/`, `scripts/`, `sql/`, `domain/` |
| Metadata store | UC `tenants` table + `.demo-secrets.env` flat file | Lakebase: `client_registry`, `sp_credentials` (AES-GCM), `audit_log` |
| `sp_tenant_mapping` | UC Delta (unchanged) | UC Delta (unchanged — required by row filter) |
| Domain data | Hardcoded in `seed_demo.py` | `domain/<name>/` swappable layer |
| API surface | `/tenants/audit`, `/tenants/mapping` | `/audit`, `/audit/mapping`; new `/tenants/bulk`, `/tenants/{id}/{reactivate,history}`, `DELETE /tenants/{id}`, `/verify` |
| `/genie/ask` | Returns answer only | Optionally returns a six-step `inspector` block when `?inspect=true` |
| UI | Single page (Client View) | Three tabs (Demo / Admin / Architecture), Inspector hero feature |
| Branding | Customer-specific copy throughout | Generic "tenant" copy |

## Migration path

For most users: start fresh.

```bash
git stash       # if you have local changes
git pull        # or re-clone
./bootstrap.sh --demo
```

The data model is incompatible with the old version (different tables, different store), so an in-place migration would be more work than re-onboarding from scratch. The demo tenants take ~30 seconds to onboard.

## If you have production tenants on the old version

The two stores you care about are the UC `tenants` table (old) and the new Lakebase `client_registry`. The data shape is different but the SP IDs are stable.

```sql
-- 1. Dump the old UC tenants table to a CSV
SELECT tenant_id, tenant_name, sp_app_id, sp_display_name, status,
       created_at, updated_at
FROM your_catalog.your_schema.tenants;
```

Then write a one-shot script to insert into Lakebase `client_registry`:

```python
import csv, psycopg
from server.lib import db

with psycopg.connect(db.database_url()) as conn:
    with open("old-tenants.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            conn.execute(
                "INSERT INTO client_registry "
                "(tenant_id, display_name, sp_app_id, sp_display_name, status) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (row["tenant_id"], row["tenant_name"], row["sp_app_id"],
                 row["sp_display_name"], row["status"]),
            )
        conn.commit()
```

For SP credentials — the old version stored secrets in the Databricks secret scope under each SP's app ID. The new version stores them in `sp_credentials` (Lakebase, encrypted with AES-GCM). Easiest path: rotate every tenant via the Admin tab after migration, which mints fresh secrets and stores them correctly.

## What you can delete

After migrating, the legacy UC `tenants` table is no longer used. The `audit_log` UC table is no longer written to (audit goes to Lakebase). You can drop both:

```sql
DROP TABLE IF EXISTS your_catalog.your_schema.tenants;
DROP TABLE IF EXISTS your_catalog.your_schema.audit_log;
```

Don't drop `sp_tenant_mapping` — the row filter still joins it.

## What stayed the same

- `sp_tenant_mapping` schema unchanged.
- `tenant_row_filter` function unchanged.
- The bookings/customers governed-data tables (now defined in `domain/travel/schema.sql`) — unchanged structure.
- OAuth M2M flow — unchanged.
- The Pattern A core idea (SP per tenant) — unchanged.

If you want a deeper technical-decision summary, see `docs/superpowers/specs/2026-04-28-generalize-and-scale-design.md`.
