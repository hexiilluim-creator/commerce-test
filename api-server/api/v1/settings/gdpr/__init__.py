from fastapi import APIRouter

from . import export, purge, retention_policy

router = APIRouter()

router.include_router(retention_policy.router, tags=["GDPR"])
router.include_router(export.router, tags=["GDPR"])
router.include_router(purge.router, tags=["GDPR"])
