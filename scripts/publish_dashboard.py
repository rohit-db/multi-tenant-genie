#!/usr/bin/env python3
"""Create + publish the SkyDesk AI/BI (Lakeview) dashboard for external embedding.

Publishes WITHOUT embedded credentials (``embed_credentials=false``) so each
viewer's queries run as the token-minting Service Principal. Combined with the
per-tenant SP embed token minted by the app, ``session_user()`` resolves to the
tenant SP and the existing Unity Catalog row filter trims the data — no
per-tenant dashboard copies, no app-asserted filter.

The dashboard includes an "Executing identity" tile (``SELECT session_user()``)
so you can visually validate, per tenant, that the embed runs as the tenant SP.

Usage:
    python scripts/publish_dashboard.py \
        --profile <cli-profile> \
        --catalog <your-catalog> \
        --schema mt_genie_demo \
        --warehouse-id <warehouse-id> \
        [--name "SkyDesk Analytics"] [--dashboard-id <existing>]

Prints the dashboard_id to set as MT_GENIE_DASHBOARD_ID.
"""
from __future__ import annotations

import argparse
import json
import sys

from databricks.sdk import WorkspaceClient


def build_serialized_dashboard(fq: str) -> str:
    bookings = f"{fq}.bookings"

    datasets = [
        {
            "name": "summary",
            "displayName": "Summary",
            "queryLines": [
                "SELECT count(*) AS bookings, "
                "round(sum(amount_usd), 2) AS total_spend, "
                "count(DISTINCT traveler_name) AS travelers "
                f"FROM {bookings}"
            ],
        },
        {
            "name": "identity",
            "displayName": "Executing identity",
            "queryLines": [
                "SELECT session_user() AS session_user, "
                "current_user() AS current_user"
            ],
        },
        {
            "name": "routes",
            "displayName": "Top routes",
            "queryLines": [
                "SELECT route, count(*) AS trips, "
                "round(sum(amount_usd), 2) AS spend "
                f"FROM {bookings} GROUP BY route ORDER BY trips DESC LIMIT 10"
            ],
        },
        {
            "name": "cabin",
            "displayName": "Spend by cabin",
            "queryLines": [
                "SELECT cabin_class, round(sum(amount_usd), 2) AS spend "
                f"FROM {bookings} GROUP BY cabin_class ORDER BY spend DESC"
            ],
        },
    ]

    def counter(name, dataset, field, label):
        return {
            "widget": {
                "name": name,
                "queries": [
                    {
                        "name": "main_query",
                        "query": {
                            "datasetName": dataset,
                            "fields": [{"name": field, "expression": f"`{field}`"}],
                            "disaggregated": False,
                        },
                    }
                ],
                "spec": {
                    "version": 2,
                    "widgetType": "counter",
                    "encodings": {
                        "value": {"fieldName": field, "displayName": label}
                    },
                },
            },
        }

    def table(name, dataset, fields):
        return {
            "widget": {
                "name": name,
                "queries": [
                    {
                        "name": "main_query",
                        "query": {
                            "datasetName": dataset,
                            "fields": [
                                {"name": f, "expression": f"`{f}`"} for f in fields
                            ],
                            "disaggregated": True,
                        },
                    }
                ],
                "spec": {
                    "version": 1,
                    "widgetType": "table",
                    "encodings": {
                        "columns": [
                            {"fieldName": f, "displayName": f} for f in fields
                        ]
                    },
                },
            },
        }

    def bar(name, dataset, x, y, xlabel, ylabel):
        return {
            "widget": {
                "name": name,
                "queries": [
                    {
                        "name": "main_query",
                        "query": {
                            "datasetName": dataset,
                            "fields": [
                                {"name": x, "expression": f"`{x}`"},
                                {"name": y, "expression": f"SUM(`{y}`)"},
                            ],
                            "disaggregated": False,
                        },
                    }
                ],
                "spec": {
                    "version": 3,
                    "widgetType": "bar",
                    "encodings": {
                        "x": {
                            "fieldName": x,
                            "scale": {"type": "categorical"},
                            "displayName": xlabel,
                        },
                        "y": {
                            "fieldName": y,
                            "scale": {"type": "quantitative"},
                            "displayName": ylabel,
                        },
                    },
                },
            },
        }

    def at(widget, x, y, w, h):
        widget = dict(widget)
        widget["position"] = {"x": x, "y": y, "width": w, "height": h}
        return widget

    layout = [
        at(counter("c_bookings", "summary", "bookings", "Bookings"), 0, 0, 2, 3),
        at(counter("c_spend", "summary", "total_spend", "Total spend (USD)"), 2, 0, 2, 3),
        at(counter("c_travelers", "summary", "travelers", "Travelers"), 4, 0, 2, 3),
        at(bar("b_routes", "routes", "route", "trips", "Route", "Trips"), 0, 3, 3, 6),
        at(bar("b_cabin", "cabin", "cabin_class", "spend", "Cabin", "Spend (USD)"), 3, 3, 3, 6),
        at(
            table("t_identity", "identity", ["session_user", "current_user"]),
            0,
            9,
            6,
            3,
        ),
    ]

    dashboard = {
        "datasets": datasets,
        "pages": [
            {"name": "overview", "displayName": "Overview", "layout": layout}
        ],
    }
    return json.dumps(dashboard)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--warehouse-id", required=True)
    ap.add_argument("--name", default="SkyDesk Analytics")
    ap.add_argument("--dashboard-id", default=None, help="update an existing draft")
    args = ap.parse_args()

    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    fq = f"{args.catalog}.{args.schema}"
    serialized = build_serialized_dashboard(fq)

    if args.dashboard_id:
        dash = w.api_client.do(
            "PATCH",
            f"/api/2.0/lakeview/dashboards/{args.dashboard_id}",
            body={"serialized_dashboard": serialized, "warehouse_id": args.warehouse_id},
        )
        dashboard_id = args.dashboard_id
    else:
        dash = w.api_client.do(
            "POST",
            "/api/2.0/lakeview/dashboards",
            body={
                "display_name": args.name,
                "warehouse_id": args.warehouse_id,
                "serialized_dashboard": serialized,
            },
        )
        dashboard_id = dash["dashboard_id"]

    # Publish WITHOUT embedded credentials — the critical setting.
    w.api_client.do(
        "POST",
        f"/api/2.0/lakeview/dashboards/{dashboard_id}/published",
        body={"embed_credentials": False, "warehouse_id": args.warehouse_id},
    )

    print(f"\n✅ Published dashboard: {dashboard_id}")
    print(f"   embed_credentials=false (queries run as the viewing SP)")
    print(f"\nSet this and redeploy:")
    print(f"   MT_GENIE_DASHBOARD_ID={dashboard_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
