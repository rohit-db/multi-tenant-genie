"""Bootstrap the multi-tenant Genie demo.

Run once on a fresh workspace to:
    1. Create the UC schema + tables
    2. Apply the Pattern A row filter to bookings/customers
    3. Onboard three demo tenants (each gets a real SP + OAuth secret)
    4. Seed synthetic bookings / customers for each tenant

Usage
-----
    python -m src.scripts.seed_demo

Idempotent: re-running skips tenants that already exist and appends
bookings only when the tables are empty.
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow `python -m src.scripts.seed_demo` or direct invocation
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from server.lib.config import CONFIG  # noqa: E402
from server.lib.sp_manager import SPManager  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed")

DEMO_TENANTS = [
    {"tenant_id": "nike", "tenant_name": "Nike",
     "industry": "Retail / Apparel", "hq": "Beaverton, OR", "travelers": 840},
    {"tenant_id": "cloudventure", "tenant_name": "CloudVenture",
     "industry": "Technology", "hq": "Austin, TX", "travelers": 312},
    {"tenant_id": "acme", "tenant_name": "Acme Industrial",
     "industry": "Manufacturing", "hq": "Cleveland, OH", "travelers": 158},
]

ROUTES = [
    ("SEA", "JFK"), ("SEA", "LHR"), ("SFO", "NRT"), ("SFO", "FRA"),
    ("ORD", "LAX"), ("AUS", "DEN"), ("DFW", "BOS"), ("LGA", "MIA"),
    ("PDX", "SFO"), ("CLE", "ATL"), ("DTW", "LHR"), ("ATL", "CDG"),
]
SUPPLIERS = ["Delta", "United", "American", "British Airways", "Lufthansa", "ANA"]
CABINS = ["Economy", "Premium Economy", "Business", "First"]


def _sql_exec(mgr: SPManager, stmt: str) -> None:
    mgr._execute_sql(stmt)


def setup_schema(mgr: SPManager) -> None:
    log.info("Creating schema %s.%s", CONFIG.catalog, CONFIG.schema)
    _sql_exec(
        mgr,
        f"CREATE SCHEMA IF NOT EXISTS {CONFIG.catalog}.{CONFIG.schema} "
        f"COMMENT 'Multi-tenant Genie SP-management demo'",
    )

    _sql_exec(mgr, f"""
        CREATE TABLE IF NOT EXISTS {CONFIG.fq_tenants} (
            tenant_id STRING NOT NULL,
            tenant_name STRING NOT NULL,
            sp_app_id STRING NOT NULL,
            sp_display_name STRING NOT NULL,
            status STRING NOT NULL,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        ) USING DELTA
    """)
    _sql_exec(mgr, f"""
        CREATE TABLE IF NOT EXISTS {CONFIG.fq_mapping} (
            sp_app_id STRING NOT NULL,
            tenant_id STRING NOT NULL,
            active BOOLEAN NOT NULL
        ) USING DELTA
    """)
    _sql_exec(mgr, f"""
        CREATE TABLE IF NOT EXISTS {CONFIG.fq_bookings} (
            booking_id STRING NOT NULL,
            tenant_id STRING NOT NULL,
            traveler_name STRING,
            origin STRING,
            destination STRING,
            route STRING,
            supplier STRING,
            cabin_class STRING,
            amount_usd DOUBLE,
            booked_at TIMESTAMP
        ) USING DELTA
    """)
    _sql_exec(mgr, f"""
        CREATE TABLE IF NOT EXISTS {CONFIG.fq_customers} (
            tenant_id STRING NOT NULL,
            customer_segment STRING,
            industry STRING,
            headquartered_in STRING,
            active_travelers INT
        ) USING DELTA
    """)
    _sql_exec(mgr, f"""
        CREATE TABLE IF NOT EXISTS {CONFIG.fq_audit} (
            event_time TIMESTAMP NOT NULL,
            actor STRING,
            tenant_id STRING,
            action STRING,
            sp_app_id STRING,
            question STRING,
            latency_ms INT,
            status STRING,
            detail STRING
        ) USING DELTA
    """)


def apply_row_filter(mgr: SPManager) -> None:
    log.info("Applying row filter function + binding to bookings/customers")
    # Function parameter must be named distinctly from the column being filtered
    # so we can reference it unambiguously inside EXISTS.
    _sql_exec(mgr, f"""
        CREATE OR REPLACE FUNCTION {CONFIG.fq_row_filter}(tenant_param STRING)
        RETURN
          is_account_group_member('{CONFIG.admin_group}')
          OR EXISTS (
            SELECT 1 FROM {CONFIG.fq_mapping} m
            WHERE m.sp_app_id = session_user()
              AND m.active = true
              AND m.tenant_id = tenant_param
          )
    """)
    for tbl in (CONFIG.fq_bookings, CONFIG.fq_customers):
        # DROP any prior filter first so re-runs don't fail
        try:
            _sql_exec(mgr, f"ALTER TABLE {tbl} DROP ROW FILTER")
        except Exception:
            pass
        _sql_exec(
            mgr,
            f"ALTER TABLE {tbl} SET ROW FILTER {CONFIG.fq_row_filter} ON (tenant_id)",
        )


def onboard_tenants(mgr: SPManager) -> dict[str, str]:
    existing = {t.tenant_id: t for t in mgr.list_tenants()}
    secrets: dict[str, str] = {}
    for t in DEMO_TENANTS:
        if t["tenant_id"] in existing:
            tenant = existing[t["tenant_id"]]
            log.info("Tenant %s already onboarded (sp=%s)", t["tenant_id"], tenant.sp_app_id)
            # Rotate to refresh the stored secret so we know it still works
            secret = mgr.rotate_secret(t["tenant_id"])
            secrets[t["tenant_id"]] = secret
        else:
            log.info("Onboarding %s…", t["tenant_id"])
            result = mgr.onboard_tenant(t["tenant_id"], t["tenant_name"])
            secrets[t["tenant_id"]] = result.client_secret
    return secrets


def grant_access(mgr: SPManager) -> None:
    log.info("Granting SELECT on demo tables to tenant SPs")
    mgr.grant_data_access()


def seed_customers(mgr: SPManager) -> None:
    rows = mgr._execute_sql(f"SELECT count(*) FROM {CONFIG.fq_customers}")
    if rows and int(rows[0][0]) > 0:
        log.info("Customers already seeded — skipping")
        return
    for t in DEMO_TENANTS:
        _sql_exec(mgr, f"""
            INSERT INTO {CONFIG.fq_customers}
              (tenant_id, customer_segment, industry, headquartered_in, active_travelers)
            VALUES ('{t['tenant_id']}', 'Enterprise',
                    '{t['industry']}', '{t['hq']}', {t['travelers']})
        """)


def seed_bookings(mgr: SPManager, n_per_tenant: int = 250) -> None:
    rows = mgr._execute_sql(f"SELECT count(*) FROM {CONFIG.fq_bookings}")
    if rows and int(rows[0][0]) > 0:
        log.info("Bookings already seeded — skipping")
        return

    random.seed(42)
    now = datetime.now(timezone.utc)
    values: list[str] = []
    for t in DEMO_TENANTS:
        for i in range(n_per_tenant):
            route = random.choice(ROUTES)
            amount = round(random.uniform(220, 4800), 2)
            booked_at = (now - timedelta(days=random.randint(0, 180))).isoformat()
            values.append(
                f"('{t['tenant_id']}-{i:04d}', '{t['tenant_id']}', "
                f"'Traveler {i:03d}', '{route[0]}', '{route[1]}', "
                f"'{route[0]}-{route[1]}', '{random.choice(SUPPLIERS)}', "
                f"'{random.choice(CABINS)}', {amount}, TIMESTAMP'{booked_at}')"
            )
    # Insert in chunks of 100 rows to keep each statement small
    log.info("Inserting %d synthetic bookings across %d tenants",
             len(values), len(DEMO_TENANTS))
    for i in range(0, len(values), 100):
        chunk = ",".join(values[i : i + 100])
        _sql_exec(
            mgr,
            f"""INSERT INTO {CONFIG.fq_bookings}
                (booking_id, tenant_id, traveler_name, origin, destination,
                 route, supplier, cabin_class, amount_usd, booked_at)
                VALUES {chunk}""",
        )


def persist_secrets_sidecar(secrets: dict[str, str]) -> None:
    """Dump SP secrets to a local file so the Streamlit UI can start fast.

    In a real deployment the Streamlit app would read these from the
    ${scope} secret scope at request time. For the demo we write a
    local file so the admin doesn't have to copy/paste client_ids
    manually. File is git-ignored.
    """
    out = _REPO / ".demo-secrets.env"
    with out.open("w") as f:
        for tenant_id, secret in secrets.items():
            f.write(f"MT_GENIE_SECRET_{tenant_id.upper()}={secret}\n")
    log.info("Wrote sidecar secrets to %s", out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-onboard", action="store_true",
                    help="Skip SP onboarding (only bootstrap schema/data)")
    ap.add_argument("--bookings-per-tenant", type=int, default=250)
    args = ap.parse_args()

    t0 = time.time()
    mgr = SPManager()

    setup_schema(mgr)
    apply_row_filter(mgr)
    secrets: dict[str, str] = {}
    if not args.skip_onboard:
        secrets = onboard_tenants(mgr)
        grant_access(mgr)
        persist_secrets_sidecar(secrets)
    seed_customers(mgr)
    seed_bookings(mgr, n_per_tenant=args.bookings_per_tenant)

    log.info("Done in %.1fs", time.time() - t0)
    print("\nOnboarded tenants:")
    for t in mgr.list_tenants():
        print(f"  {t.tenant_id:16s} status={t.status:12s} sp_app_id={t.sp_app_id}")


if __name__ == "__main__":
    main()
