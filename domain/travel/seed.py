# domain/travel/seed.py
"""Travel-domain seed logic. Imported via the domain registry."""
from __future__ import annotations

import logging
import random
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


def seed(mgr, tenants: Iterable[dict]) -> None:
    """Seed bookings + customers for each tenant. ``mgr`` is an SPManager."""
    from server.lib.config import CONFIG

    for t in tenants:
        tid = t['tenant_id']
        # customers row
        mgr._execute_sql(
            f"INSERT INTO {CONFIG.catalog}.{CONFIG.schema}.customers "
            f"(tenant_id, customer_segment, industry, headquartered_in, active_travelers) "
            f"VALUES ('{tid}', 'enterprise', '{t.get('industry', 'Other')}', "
            f"'{t.get('hq', '—')}', {int(t.get('travelers', 100))})"
        )
        # bookings rows
        n = max(50, int(t.get('travelers', 100)) // 4)
        for _ in range(n):
            origin, dest = random.choice(ROUTES)
            supplier = random.choice(SUPPLIERS)
            cabin = random.choice(CABINS)
            amount = round(random.uniform(180, 9800), 2)
            booked = datetime.now(timezone.utc) - timedelta(days=random.randint(1, 365))
            mgr._execute_sql(
                f"INSERT INTO {CONFIG.catalog}.{CONFIG.schema}.bookings "
                f"(booking_id, tenant_id, traveler_name, origin, destination, route, supplier, cabin_class, amount_usd, booked_at) "
                f"VALUES (uuid(), '{tid}', 'Traveler', '{origin}', '{dest}', "
                f"'{origin}-{dest}', '{supplier}', '{cabin}', {amount}, "
                f"TIMESTAMP'{booked.isoformat()}')"
            )
