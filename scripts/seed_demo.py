"""Bootstrap the multi-tenant Genie demo for the active domain.

Run after `docker compose up -d` (for Lakebase locally) and a workspace
profile that points at your target Databricks workspace.

Steps:
    1. Apply Lakebase migrations.
    2. Apply UC schema (sql/setup.sql + active domain's schema.sql).
    3. Onboard the demo tenants (writes to UC mapping + Lakebase registry + credentials).
    4. Run the active domain's seed() to populate per-tenant data.

Idempotent: re-running skips already-onboarded tenants and re-seeds only
empty tables.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from server.lib import db, domain  # noqa: E402
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


def apply_lakebase_migrations():
    log.info("Applying Lakebase migrations from sql/lakebase/")
    db.apply_migrations(_REPO / "sql" / "lakebase")


def apply_uc_schema(mgr: SPManager, dom: domain.Domain):
    log.info("Applying UC schema (sql/setup.sql)")
    sql = (_REPO / "sql" / "setup.sql").read_text()
    sql = sql.replace("${catalog}", CONFIG.catalog).replace(
        "${schema}", CONFIG.schema
    ).replace("${admin_group}", CONFIG.admin_group)
    for stmt in (s.strip() for s in sql.split(";") if s.strip()):
        mgr._execute_sql(stmt)

    log.info("Applying domain schema (%s)", dom.schema_sql_path)
    dsql = dom.schema_sql_path.read_text()
    dsql = dsql.replace("${catalog}", CONFIG.catalog).replace(
        "${schema}", CONFIG.schema
    )
    for stmt in (s.strip() for s in dsql.split(";") if s.strip()):
        mgr._execute_sql(stmt)


def onboard_demo_tenants(mgr: SPManager):
    from server.lib.repository import tenant as tenant_repo
    for spec in DEMO_TENANTS:
        if tenant_repo.get(spec["tenant_id"]):
            log.info("Tenant %s already exists — skipping onboard", spec["tenant_id"])
            continue
        log.info("Onboarding %s", spec["tenant_id"])
        mgr.onboard_tenant(spec["tenant_id"], spec["tenant_name"])
        mgr.grant_data_access([spec["tenant_id"]])
        mgr.grant_genie_access([spec["tenant_id"]])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--skip-uc", action="store_true",
                   help="Skip UC schema setup (use when only re-seeding data)")
    p.add_argument("--skip-onboard", action="store_true",
                   help="Skip tenant onboarding")
    args = p.parse_args()

    apply_lakebase_migrations()
    mgr = SPManager()
    dom = domain.load()
    log.info("Active domain: %s", dom.name)

    if not args.skip_uc:
        apply_uc_schema(mgr, dom)
    if not args.skip_onboard:
        onboard_demo_tenants(mgr)

    log.info("Seeding %s data for %d tenants", dom.name, len(DEMO_TENANTS))
    dom.seed_callable(mgr, DEMO_TENANTS)
    log.info("Done.")


if __name__ == "__main__":
    main()
