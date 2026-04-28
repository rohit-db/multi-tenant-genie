"""Workspace / config info for the UI header."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.lib.config import CONFIG  # noqa: E402

router = APIRouter()


class WorkspaceInfo(BaseModel):
    host: str
    catalog: str
    schema_name: str
    genie_space_id: str
    warehouse_name: str
    admin_group: str


@router.get('/info', response_model=WorkspaceInfo)
async def workspace_info() -> WorkspaceInfo:
    return WorkspaceInfo(
        host=CONFIG.host,
        catalog=CONFIG.catalog,
        schema_name=CONFIG.schema,
        genie_space_id=CONFIG.genie_space_id,
        warehouse_name=CONFIG.warehouse_name,
        admin_group=CONFIG.admin_group,
    )
