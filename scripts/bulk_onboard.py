"""Bulk onboard tenants for the multi-tenant Genie demo.

Creates N service principals, mints OAuth secrets, persists them, and
registers SP→tenant mappings — designed for realistic scale (hundreds
to thousands) with idempotency, bounded concurrency, 429 retry, and a
per-tenant outcome report.

DOCUMENTED RATE LIMITS THIS SCRIPT RESPECTS
-------------------------------------------
* Account SCIM API (used for SP create / secret mint):
    POST / PUT / DELETE → 5 per second
    https://docs.databricks.com/aws/en/resources/limits
* Genie Conversation API:
    5 questions per minute per workspace (not exercised by onboarding,
    but the same workspace is the call surface so worth knowing)
    https://docs.databricks.com/aws/en/genie/conversation-api
* OAuth /oidc/v1/token: not formally documented; generally generous.

The default ``--workers 5`` matches the POST rate budget. Increase only
if you spread requests across multiple account-API hosts (uncommon).

USAGE
-----
    # Dry-run a plan for 500 generated tenants — no mutation
    python -m src.scripts.bulk_onboard --count 500 --dry-run

    # Real run from a CSV
    python -m src.scripts.bulk_onboard --input tenants.csv

    # Real run, custom concurrency + report path
    python -m src.scripts.bulk_onboard --count 100 \\
        --workers 5 --chunk 50 --report bulk-report.json

CSV / JSON INPUT FORMAT
-----------------------
CSV (header required):
    tenant_id,tenant_name
    acme,Acme Corp
    globex,Globex Industries

JSON:
    [{"tenant_id": "acme", "tenant_name": "Acme Corp"}, ...]

OUTPUT
------
* ``.demo-secrets.env`` is appended/updated with new SP secrets.
* ``--report PATH`` writes per-tenant outcomes (default
  ``bulk-onboard-report.json``).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Allow ``python -m src.scripts.bulk_onboard`` and direct invocation.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from server.lib.config import CONFIG  # noqa: E402
from server.lib.sp_manager import SPManager  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("bulk_onboard")

SECRETS_FILE = _REPO / ".demo-secrets.env"

# Retry config for 429s (and transient network errors).
MAX_RETRIES = 4
BASE_BACKOFF_S = 1.0


@dataclass
class TenantInput:
    tenant_id: str
    tenant_name: str


@dataclass
class Outcome:
    tenant_id: str
    tenant_name: str
    ok: bool
    sp_app_id: str | None = None
    client_secret: str | None = None  # captured ONLY in-memory; persisted to file
    error: str | None = None
    duration_s: float = 0.0
    attempts: int = 1


# --------------------------------------------------------------------- I/O
def _load_csv(path: Path) -> list[TenantInput]:
    with path.open() as fh:
        reader = csv.DictReader(fh)
        return [
            TenantInput(
                tenant_id=row["tenant_id"].strip().lower(),
                tenant_name=row["tenant_name"].strip(),
            )
            for row in reader
            if row.get("tenant_id")
        ]


def _load_json(path: Path) -> list[TenantInput]:
    data = json.loads(path.read_text())
    return [
        TenantInput(
            tenant_id=str(row["tenant_id"]).strip().lower(),
            tenant_name=str(row["tenant_name"]).strip(),
        )
        for row in data
    ]


def _generate(count: int) -> list[TenantInput]:
    """Auto-generate plausible tenant rows for scale demos."""
    return [
        TenantInput(tenant_id=f"bulk-{i:04d}", tenant_name=f"Bulk Tenant {i:04d}")
        for i in range(1, count + 1)
    ]


def _load_input(args: argparse.Namespace) -> list[TenantInput]:
    if args.input:
        p = Path(args.input)
        if p.suffix.lower() == ".json":
            return _load_json(p)
        return _load_csv(p)
    if args.count:
        return _generate(args.count)
    raise SystemExit("Provide either --input <file> or --count <N>")


def _load_existing_secrets() -> dict[str, str]:
    if not SECRETS_FILE.exists():
        return {}
    out: dict[str, str] = {}
    for line in SECRETS_FILE.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _save_secrets(secrets: dict[str, str]) -> None:
    SECRETS_FILE.write_text(
        "\n".join(f"{k}={v}" for k, v in secrets.items()) + "\n"
    )


def _secret_key(tenant_id: str) -> str:
    return f"MT_GENIE_SECRET_{tenant_id.upper()}"


# --------------------------------------------------------------------- core
def _is_rate_limited(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate limit" in msg


def _onboard_one(mgr: SPManager, t: TenantInput) -> Outcome:
    """Onboard a single tenant with 429 retry + exponential backoff."""
    started = time.time()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = mgr.onboard_tenant(t.tenant_id, t.tenant_name)
            return Outcome(
                tenant_id=t.tenant_id,
                tenant_name=t.tenant_name,
                ok=True,
                sp_app_id=result.tenant.sp_app_id,
                client_secret=result.client_secret,
                duration_s=time.time() - started,
                attempts=attempt,
            )
        except Exception as e:
            if _is_rate_limited(e) and attempt < MAX_RETRIES:
                # Exponential backoff with jitter.
                delay = BASE_BACKOFF_S * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                log.warning(
                    "rate-limited on %s (attempt %d/%d); sleeping %.1fs",
                    t.tenant_id, attempt, MAX_RETRIES, delay,
                )
                time.sleep(delay)
                continue
            return Outcome(
                tenant_id=t.tenant_id,
                tenant_name=t.tenant_name,
                ok=False,
                error=str(e),
                duration_s=time.time() - started,
                attempts=attempt,
            )
    # Exhausted retries
    return Outcome(
        tenant_id=t.tenant_id,
        tenant_name=t.tenant_name,
        ok=False,
        error="exceeded retry budget",
        duration_s=time.time() - started,
        attempts=MAX_RETRIES,
    )


def _print_plan(
    inputs: list[TenantInput], existing: set[str], args: argparse.Namespace
) -> None:
    new = [t for t in inputs if t.tenant_id not in existing]
    skipped = [t for t in inputs if t.tenant_id in existing]
    print("=" * 60)
    print("DRY RUN — no changes will be made")
    print("=" * 60)
    print(f"Workspace      : {CONFIG.host}")
    print(f"Catalog/schema : {CONFIG.catalog}.{CONFIG.schema}")
    print(f"Workers        : {args.workers}")
    print(f"Chunk size     : {args.chunk}")
    print()
    print(f"Input rows                 : {len(inputs)}")
    print(f"Already onboarded (skip)   : {len(skipped)}")
    print(f"Will be created            : {len(new)}")
    print()
    # SP creation is the binding rate. ~5 SP creates/sec/account at peak.
    est_seconds = max(1, len(new) // 5)
    print(f"Estimated wall time (best) : ~{est_seconds}s "
          "(assumes 5 SP creates/sec, no 429 retries)")
    print(f"Likely wall time           : {est_seconds * 2}-{est_seconds * 4}s "
          "(network + UC writes + occasional retries)")
    print()
    print("Sample of first 5:")
    for t in new[:5]:
        print(f"  + {t.tenant_id}  →  {t.tenant_name}")
    if len(new) > 5:
        print(f"  … and {len(new) - 5} more")


def _summarize(results: list[Outcome]) -> None:
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    durations = [r.duration_s for r in ok]
    rate_limited = sum(1 for r in results if r.attempts > 1)
    print()
    print("=" * 60)
    print("BULK ONBOARDING SUMMARY")
    print("=" * 60)
    print(f"Total           : {len(results)}")
    print(f"Succeeded       : {len(ok)}")
    print(f"Failed          : {len(failed)}")
    print(f"Hit 429 retry   : {rate_limited}")
    if durations:
        print(f"Per-tenant time : min={min(durations):.2f}s "
              f"avg={sum(durations)/len(durations):.2f}s "
              f"max={max(durations):.2f}s")
    if failed:
        print()
        print("Failures (first 10):")
        for r in failed[:10]:
            print(f"  ✗ {r.tenant_id}  →  {r.error[:120] if r.error else ''}")


def _write_report(results: list[Outcome], path: Path) -> None:
    """Per-tenant outcome JSON. Note: client_secret is included; protect this file."""
    serializable = [asdict(r) for r in results]
    path.write_text(json.dumps(serializable, indent=2, default=str))
    log.info("Wrote report to %s (contains secrets — chmod 600 recommended)", path)


# --------------------------------------------------------------------- main
def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Bulk onboard tenants. Respects documented rate limits and is "
            "idempotent: existing tenant_ids are skipped."
        )
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="CSV or JSON file with tenant_id,tenant_name")
    src.add_argument("--count", type=int, help="Auto-generate N tenants (bulk-NNNN)")
    p.add_argument("--dry-run", action="store_true", help="Print plan and exit")
    p.add_argument(
        "--workers", type=int, default=5,
        help="Concurrent onboard workers (default 5; matches account SCIM POST limit)",
    )
    p.add_argument(
        "--chunk", type=int, default=50,
        help="Tenants per chunk before pausing for grants (default 50)",
    )
    p.add_argument(
        "--no-genie-grant", action="store_true",
        help="Skip Genie space CAN_RUN grant (saves one PATCH per chunk)",
    )
    p.add_argument(
        "--no-data-grant", action="store_true",
        help="Skip UC GRANT statements (only safe if SPs inherit via group)",
    )
    p.add_argument(
        "--report", default="bulk-onboard-report.json",
        help="Output report path (per-tenant outcomes, default bulk-onboard-report.json)",
    )
    args = p.parse_args()

    inputs = _load_input(args)

    log.info("Loaded %d tenant rows", len(inputs))

    mgr = SPManager()
    existing = {t.tenant_id for t in mgr.list_tenants()}

    if args.dry_run:
        _print_plan(inputs, existing, args)
        return 0

    new = [t for t in inputs if t.tenant_id not in existing]
    if existing & {t.tenant_id for t in inputs}:
        log.info("Skipping %d already-onboarded tenants",
                 len(inputs) - len(new))

    if not new:
        log.info("Nothing to do.")
        return 0

    # Pre-create the secret scope so worker threads don't race on first run.
    log.info("Ensuring secret scope %s exists…", CONFIG.secret_scope)
    mgr._ensure_secret_scope()

    log.info("Starting bulk onboard: %d tenants, %d workers, chunks of %d",
             len(new), args.workers, args.chunk)

    secrets = _load_existing_secrets()
    all_results: list[Outcome] = []

    # Process in chunks so we can run grants periodically and bound the
    # blast radius of any persistent failures (e.g. workspace outage).
    for chunk_idx in range(0, len(new), args.chunk):
        chunk = new[chunk_idx : chunk_idx + args.chunk]
        chunk_no = chunk_idx // args.chunk + 1
        chunks_total = (len(new) + args.chunk - 1) // args.chunk
        log.info("--- Chunk %d/%d (%d tenants) ---",
                 chunk_no, chunks_total, len(chunk))

        results: list[Outcome] = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_onboard_one, mgr, t): t for t in chunk}
            done = 0
            for f in as_completed(futures):
                r = f.result()
                results.append(r)
                done += 1
                if r.ok:
                    secrets[_secret_key(r.tenant_id)] = r.client_secret  # type: ignore[assignment]
                if done % 10 == 0 or done == len(chunk):
                    succ = sum(1 for x in results if x.ok)
                    log.info("  progress: %d/%d done (%d ok, %d failed)",
                             done, len(chunk), succ, done - succ)

        # Persist secrets after every chunk so a mid-run crash doesn't lose them.
        _save_secrets(secrets)
        all_results.extend(results)

        # Batched grants for this chunk's successes (one PATCH for Genie,
        # multiple GRANTs for data — both are O(N) statements but each one
        # carries multiple principals where possible).
        succeeded = [r.tenant_id for r in results if r.ok]
        if succeeded:
            if not args.no_data_grant:
                log.info("  granting UC data access (%d tenants)…", len(succeeded))
                try:
                    mgr.grant_data_access(succeeded)
                except Exception as e:
                    log.error("  data grant failed: %s", e)
            if not args.no_genie_grant and CONFIG.genie_space_id:
                log.info("  granting Genie CAN_RUN (1 PATCH for %d SPs)…",
                         len(succeeded))
                try:
                    mgr.grant_genie_access(succeeded)
                except Exception as e:
                    log.error("  Genie grant failed: %s", e)

    _write_report(all_results, Path(args.report))
    _summarize(all_results)

    failed = sum(1 for r in all_results if not r.ok)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
