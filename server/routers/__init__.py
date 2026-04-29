"""Multi-Tenant Genie — API router."""

from fastapi import APIRouter

from .tenants import router as tenants_router
from .genie import router as genie_router
from .workspace import router as workspace_router
from .jobs import router as jobs_router
from .audit import router as audit_router
from .verify import router as verify_router

router = APIRouter()
router.include_router(tenants_router, prefix='/tenants', tags=['tenants'])
router.include_router(genie_router, prefix='/genie', tags=['genie'])
router.include_router(workspace_router, prefix='/workspace', tags=['workspace'])
router.include_router(jobs_router, prefix='/jobs', tags=['jobs'])
router.include_router(audit_router, prefix='/audit', tags=['audit'])
router.include_router(verify_router, prefix='/verify', tags=['verify'])
