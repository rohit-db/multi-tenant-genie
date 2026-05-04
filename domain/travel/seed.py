# domain/travel/seed.py
"""Travel-domain seed logic. Imported via the domain registry."""
from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

log = logging.getLogger(__name__)

ROUTES = [
    ('SEA', 'JFK'), ('SEA', 'LHR'), ('SFO', 'NRT'), ('SFO', 'FRA'),
    ('ORD', 'LAX'), ('AUS', 'DEN'), ('DFW', 'BOS'), ('LGA', 'MIA'),
    ('PDX', 'SFO'), ('CLE', 'ATL'), ('DTW', 'LHR'), ('ATL', 'CDG'),
]
SUPPLIERS = ['Delta', 'United', 'American', 'British Airways', 'Lufthansa', 'ANA']
CABINS = ['Economy', 'Premium Economy', 'Business', 'First']
FIRST_NAMES = [
    'Alex', 'Bailey', 'Casey', 'Drew', 'Ellis', 'Finley', 'Gray',
    'Harper', 'Indigo', 'Jordan', 'Kai', 'Logan', 'Morgan', 'Nile',
    'Oakley', 'Parker', 'Quinn', 'Riley', 'Sage', 'Tatum', 'Reese',
]
LAST_NAMES = [
    'Singh', 'Patel', 'Garcia', 'Chen', 'Smith', 'Cohen', 'Nguyen',
    'Johnson', 'Lee', 'Taylor', 'Brown', 'Davis', 'Miller', 'Wilson',
    'Anderson', 'Khan', 'Rivera', 'Martin', 'Yamada', 'Müller',
]
BATCH_SIZE = 25  # rows per INSERT statement; balance roundtrip vs statement size


def _sql_str(s: str) -> str:
    """Quote a string literal for inlining in a Spark SQL VALUES row."""
    return "'" + s.replace("'", "''") + "'"


def seed(mgr, tenants: Iterable[dict]) -> None:
    """Seed bookings + customers for each tenant. ``mgr`` is an SPManager.

    UUIDs are generated in Python (Spark SQL VALUES can't evaluate
    nondeterministic expressions like uuid()). Inserts are batched into
    multi-row VALUES clauses to keep the wall time under ~30s for the
    three demo tenants.
    """
    from server.lib.config import CONFIG

    for t in tenants:
        tid = t['tenant_id']
        rng = random.Random(f"travel-seed-{tid}")  # per-tenant deterministic
        n_travelers = int(t.get('travelers', 100))

        log.info("Seeding %s: 1 customer row + %d bookings",
                 tid, max(50, n_travelers // 4))

        # customers row (single insert)
        mgr._execute_sql(
            f"INSERT INTO {CONFIG.catalog}.{CONFIG.schema}.customers "
            f"(tenant_id, customer_segment, industry, headquartered_in, active_travelers) "
            f"VALUES ({_sql_str(tid)}, 'enterprise', "
            f"{_sql_str(str(t.get('industry', 'Other')))}, "
            f"{_sql_str(str(t.get('hq', '—')))}, "
            f"{n_travelers})"
        )

        # Build a small per-tenant traveler pool — at least 8, at most 25.
        pool_size = max(8, min(25, n_travelers // 10))
        traveler_pool = [
            f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            for _ in range(pool_size)
        ]

        # bookings rows — batched
        n_bookings = max(50, n_travelers // 4)
        rows: list[str] = []
        for _ in range(n_bookings):
            origin, dest = rng.choice(ROUTES)
            supplier = rng.choice(SUPPLIERS)
            cabin = rng.choice(CABINS)
            amount = round(rng.uniform(180, 9800), 2)
            booked = datetime.now(timezone.utc) - timedelta(days=rng.randint(1, 365))
            traveler = rng.choice(traveler_pool)
            booking_id = str(uuid.uuid4())
            rows.append(
                f"({_sql_str(booking_id)}, {_sql_str(tid)}, "
                f"{_sql_str(traveler)}, {_sql_str(origin)}, {_sql_str(dest)}, "
                f"{_sql_str(f'{origin}-{dest}')}, {_sql_str(supplier)}, "
                f"{_sql_str(cabin)}, {amount}, "
                f"TIMESTAMP{_sql_str(booked.isoformat())})"
            )

        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            mgr._execute_sql(
                f"INSERT INTO {CONFIG.catalog}.{CONFIG.schema}.bookings "
                f"(booking_id, tenant_id, traveler_name, origin, destination, "
                f"route, supplier, cabin_class, amount_usd, booked_at) "
                f"VALUES {', '.join(batch)}"
            )
