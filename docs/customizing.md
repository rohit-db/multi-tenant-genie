# Customizing the Reference

The repo is opinionated about *the pattern* (SP-per-tenant + UC row filters + Lakebase metadata) but flexible about *the data*. Here's how to swap each layer.

## Swap the demo domain

The demo ships travel data — bookings, customers, routes. The schema lives in `domain/travel/schema.sql`; the seed logic in `domain/travel/seed.py`; the sample questions in `domain/travel/sample_questions.json`. Nothing in `server/` or `web/` mentions "bookings" or "travel" by name.

To swap to your own domain:

1. **Copy the directory:**
   ```bash
   cp -r domain/travel domain/retail
   ```

2. **Edit `domain/retail/schema.sql`** — declare your tables with `tenant_id` as the row-filter column:
   ```sql
   CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.orders (
       order_id STRING NOT NULL,
       tenant_id STRING NOT NULL,           -- row-filter column
       sku STRING,
       amount_usd DOUBLE,
       placed_at TIMESTAMP
   ) USING DELTA;

   ALTER TABLE ${catalog}.${schema}.orders
     SET ROW FILTER ${catalog}.${schema}.tenant_row_filter ON (tenant_id);
   ```

3. **Edit `domain/retail/seed.py`** — generate per-tenant data. The function signature is `seed(mgr, tenants: Iterable[dict])` where `mgr` is an `SPManager` instance. Use `mgr._execute_sql(...)` to write to UC.

4. **Edit `domain/retail/sample_questions.json`** — questions that fit your schema:
   ```json
   {
     "row_filter_column": "tenant_id",
     "questions": [
       "How many orders did I place last quarter?",
       "Top 10 SKUs by revenue",
       "Average order value by month"
     ]
   }
   ```

5. **Activate the new domain:**
   ```bash
   echo "DOMAIN=retail" >> .env.local
   ```

6. **Re-seed:**
   ```bash
   python scripts/seed_demo.py
   ```

## Change the row-filter column

The default is `tenant_id`. If your schema uses `customer_id`, `org_id`, or anything else, three places change:

1. **`sql/setup.sql`** — the `tenant_row_filter` function definition. Update the column name.
2. **Your domain's `schema.sql`** — the `ALTER TABLE … SET ROW FILTER … ON (column)` clause.
3. **`domain/<name>/sample_questions.json`** — set `"row_filter_column"` so the UI labels stay accurate.

The proxy code itself doesn't reference the column name; UC enforces it via the row-filter SQL alone.

## Point at your existing UC data

If you already have tenant-scoped tables in UC and just want to add the multi-tenant-genie proxy in front:

1. Make sure each governed table has a `tenant_id` (or your equivalent) column on every row.
2. Run `sql/setup.sql` against your workspace — this creates `sp_tenant_mapping` + the `tenant_row_filter` function in your chosen catalog/schema.
3. Apply the row filter to your existing tables:
   ```sql
   ALTER TABLE your_catalog.your_schema.your_table
     SET ROW FILTER your_catalog.your_schema.tenant_row_filter ON (tenant_id);
   ```
4. Skip the `domain/travel/schema.sql` runner — your tables already exist. Either (a) delete the apply-domain-schema step in `scripts/seed_demo.py` or (b) make a thin `domain/<your-name>/schema.sql` that's empty / no-op.

## Change the metadata schema

`client_registry` (Lakebase) carries `tier`, `rate_limit_per_min`, and a `metadata` JSONB column. The JSONB is intentional — extend without migrations:

```python
# When onboarding
tenant_repo.insert(
    tenant_id="acme",
    display_name="Acme",
    sp_app_id=...,
    sp_display_name=...,
    metadata={"tier": "enterprise", "region": "us-east", "contact": "ops@acme.com"},
)
```

If you need columns instead of JSONB, add a new versioned migration to `sql/lakebase/V002__add_columns.sql` and the migration runner picks it up on next startup.

## Change the demo tenants

`scripts/seed_demo.py` has `DEMO_TENANTS` at the top. Edit the list — each entry is `{tenant_id, tenant_name, industry, hq, travelers}`. The travel-specific keys (`industry`, `hq`, `travelers`) are passed to `domain/travel/seed.py` as kwargs; if your domain ignores them, that's fine.

## Change the Genie space

Single-space (default): set `MT_GENIE_SPACE_ID` and that's the global default for every tenant.

Per-tenant override: the `client_registry.genie_space_id` column accepts a UUID; when set, the proxy uses it for that tenant's queries. The UI doesn't expose this yet — see [docs/future-directions.md](future-directions.md).

## Change the UI branding

`web/src/App.tsx` controls the header title, logomark, and tabs. The Inspector's amber accent on step 4 is in `web/src/components/Inspector.tsx`. Tailwind palette is the standard `slate` / `indigo` / `emerald` / `rose` / `amber` from `tailwind.config.js`.
