"""Multi-Tenant Genie — API router."""

from fastapi import APIRouter

from .tenants import router as tenants_router
from .genie import router as genie_router
from .workspace import router as workspace_router

router = APIRouter()
router.include_router(tenants_router, prefix='/tenants', tags=['tenants'])
router.include_router(genie_router, prefix='/genie', tags=['genie'])
router.include_router(workspace_router, prefix='/workspace', tags=['workspace'])
