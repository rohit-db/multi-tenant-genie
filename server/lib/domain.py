"""Domain registry — load the active dataset (e.g., travel, retail)."""
from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Domain:
    """Represents a swappable demo domain with schema, seed logic, and sample questions."""

    name: str
    sample_questions: list[str]
    row_filter_column: str
    schema_sql_path: Path
    seed_callable: Callable  # (sp_manager, tenants) -> None


def _domain_path(name: str) -> Path:
    p = REPO / 'domain' / name
    if not p.exists():
        raise FileNotFoundError(f"Domain '{name}' not found at {p}")
    return p


def load(name: str | None = None) -> Domain:
    """Load a domain by name (defaults to DOMAIN env var, then 'travel')."""
    name = name or os.environ.get('DOMAIN', 'travel')
    p = _domain_path(name)
    sq = json.loads((p / 'sample_questions.json').read_text())
    seed_mod = importlib.import_module(f'domain.{name}.seed')
    return Domain(
        name=name,
        sample_questions=sq['questions'],
        row_filter_column=sq.get('row_filter_column', 'tenant_id'),
        schema_sql_path=p / 'schema.sql',
        seed_callable=seed_mod.seed,
    )
