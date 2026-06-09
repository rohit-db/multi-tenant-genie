"""Multi-Tenant Genie — API router.

Access tiers:
- public:    /auth/*  (login/logout/me)
- any user:  /genie, /agent, /workspace, /tenants (read) — the customer product
- operator:  /verify, /audit, /jobs, /tenants (mutations) — the back-office console
"""

from fastapi import APIRouter, Depends

from server.lib.auth import current_user, require_operator

from .auth import router as auth_router
from .tenants import router as tenants_router
from .genie import router as genie_router
from .workspace import router as workspace_router
from .jobs import router as jobs_router
from .audit import router as audit_router
from .verify import router as verify_router
from .agent import router as agent_router

router = APIRouter()

# Public — login layer.
router.include_router(auth_router, prefix='/auth', tags=['auth'])

# Customer product — any authenticated user.
router.include_router(
    genie_router, prefix='/genie', tags=['genie'], dependencies=[Depends(current_user)]
)
router.include_router(
    agent_router, prefix='/agent', tags=['agent'], dependencies=[Depends(current_user)]
)
router.include_router(
    workspace_router, prefix='/workspace', tags=['workspace'],
    dependencies=[Depends(current_user)],
)
# Tenant listing is needed by the product (dropdown); mutations carry their own
# require_operator dependency at the endpoint level.
router.include_router(
    tenants_router, prefix='/tenants', tags=['tenants'], dependencies=[Depends(current_user)]
)

# Back-office console — operators only.
router.include_router(
    jobs_router, prefix='/jobs', tags=['jobs'], dependencies=[Depends(require_operator)]
)
router.include_router(
    audit_router, prefix='/audit', tags=['audit'], dependencies=[Depends(require_operator)]
)
router.include_router(
    verify_router, prefix='/verify', tags=['verify'], dependencies=[Depends(require_operator)]
)
