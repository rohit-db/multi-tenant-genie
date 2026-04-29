"""Workspace / config info for the UI header."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from server.lib.config import CONFIG

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
