#!/usr/bin/env python3
"""Create (or reuse) the edge Service Principal and write its creds into edge/.env.

The edge front door presents this SP's OAuth token to clear the Databricks Apps
OAuth proxy. It must have CAN_USE on the app — grant that separately (the
companion step in docs/edge-gateway.md), or pass --app-name to have this script
print the exact CLI command.

Uses the same workspace-SP + ``service_principal_secrets_proxy`` path the app
already uses for tenant SPs, so it works wherever the app's onboarding works.

    python scripts/create_edge_sp.py --profile <cli-profile> \
        --display-name mt-genie-edge --app-name multi-tenant-genie
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / "edge" / ".env"


def _write_env(client_id: str, client_secret: str) -> None:
    text = ENV_PATH.read_text() if ENV_PATH.exists() else ""
    if not text:
        print(f"! {ENV_PATH} not found; create it from edge/.env.example first.", file=sys.stderr)
        return
    text = re.sub(r"^EDGE_SP_CLIENT_ID=.*$", f"EDGE_SP_CLIENT_ID={client_id}", text, flags=re.M)
    text = re.sub(r"^EDGE_SP_CLIENT_SECRET=.*$", f"EDGE_SP_CLIENT_SECRET={client_secret}", text, flags=re.M)
    ENV_PATH.write_text(text)
    print(f"✓ Wrote EDGE_SP_CLIENT_ID / EDGE_SP_CLIENT_SECRET into {ENV_PATH}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="databricks CLI profile")
    ap.add_argument("--display-name", default="mt-genie-edge")
    ap.add_argument("--app-name", default=None, help="print the CAN_USE grant command for this app")
    args = ap.parse_args()

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)

    # Reuse an existing SP with this display name if present (idempotent reruns).
    existing = [sp for sp in w.service_principals.list(filter=f'displayName eq "{args.display_name}"')]
    if existing:
        sp = existing[0]
        print(f"▸ Reusing existing SP '{args.display_name}' (app_id={sp.application_id})")
    else:
        sp = w.service_principals.create(display_name=args.display_name, active=True)
        print(f"✓ Created SP '{args.display_name}' (app_id={sp.application_id})")

    secret = w.service_principal_secrets_proxy.create(service_principal_id=sp.id)
    print("✓ Minted a fresh OAuth secret for the edge SP")

    _write_env(sp.application_id, secret.secret)

    print()
    print(f"  edge SP client_id : {sp.application_id}")
    print(f"  edge SP db_id     : {sp.id}")
    print(f"  client_secret     : (written to edge/.env; shown once) {secret.secret[:6]}…")

    if args.app_name:
        print()
        print("Next: grant CAN_USE on the app to this SP, e.g.")
        grant = (
            '{"access_control_list":[{"service_principal_name":"'
            + sp.application_id
            + '","permission_level":"CAN_USE"}]}'
        )
        print(
            f"  databricks apps update-permissions {args.app_name} "
            f"-p {args.profile} --json '{grant}'"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
