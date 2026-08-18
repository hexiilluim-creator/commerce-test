"""api/v1/omnicall_v9_admin.py — Monitoring et Administration OmniCall V9 (BLOC 8 + BLOC 9 Fast-Track)."""
from __future__ import annotations

import os

from fastapi import APIRouter

from api.v1._deps import require_role
from omnicall_v9.auto_promoter import get_promotion_report
from omnicall_v9.circuit_breaker import v9_circuit
from omnicall_v9.flags.registry import get_beta_store_ids, get_rollout_pct
from omnicall_v9.observability.shadow_observer import get_shadow_observer

router = APIRouter(prefix="/omnicall-v9", tags=["OmniCall V9 Admin"])

# Tous les endpoints V9 admin nécessitent le rôle super_admin
_require_super_admin = require_role("super_admin", "admin")


@router.get("/report", dependencies=[_require_super_admin])
async def get_v9_report():
    """Rapport complet de santé et de readiness pour le rollout."""
    observer = get_shadow_observer()
    circuit_safe = v9_circuit.is_v9_safe()

    return {
        "observer": observer.get_report(),
        "promotion_readiness": get_promotion_report(),
        "rollout": {
            "shadow_mode": os.environ.get("OMNICALL_V9_SHADOW_MODE", "0"),
            "enabled": os.environ.get("OMNICALL_V9_ENABLED", "0"),
            "rollout_pct": get_rollout_pct(),
            "beta_stores": sorted(get_beta_store_ids()),
        },
        "circuit_breaker": {
            "is_safe": circuit_safe,
            "status": "CLOSED (Safe)" if circuit_safe else "OPEN (Unsafe - V9 Disabled)",
        },
    }


@router.get("/status", dependencies=[_require_super_admin])
async def get_v9_status():
    """État actuel des feature flags V9."""
    return {
        "OMNICALL_V9_SHADOW_MODE": os.environ.get("OMNICALL_V9_SHADOW_MODE", "0"),
        "OMNICALL_V9_ENABLED": os.environ.get("OMNICALL_V9_ENABLED", "0"),
        "OMNICALL_V9_ROLLOUT_PCT": str(get_rollout_pct()),
        "OMNICALL_V9_BETA_STORES": os.environ.get("OMNICALL_V9_BETA_STORES", ""),
    }


@router.get("/flags", dependencies=[_require_super_admin])
async def get_v9_flags():
    """Détail des feature flags et guide de progression BLOC 9."""
    rollout_pct = get_rollout_pct()
    beta_stores = sorted(get_beta_store_ids())

    return {
        "flags": {
            "shadow_mode": os.environ.get("OMNICALL_V9_SHADOW_MODE", "0"),
            "enabled": os.environ.get("OMNICALL_V9_ENABLED", "0"),
            "rollout_pct": rollout_pct,
            "beta_stores": beta_stores,
            "dual_read": os.environ.get("OMNICALL_V9_DUAL_READ", "0"),
        },
        "guide": {
            "step_1": "Activer shadow mode 1 a 3 jours minimum",
            "step_2": "Activer beta stores de confiance",
            "step_3": "Monter a 5 puis 10 pourcent si les logs restent propres",
            "rollback": "Remettre OMNICALL_V9_ENABLED=0 pour revenir a V8 uniquement",
        },
    }


@router.post("/report/reset", dependencies=[_require_super_admin])
async def reset_v9_report():
    """Réinitialise les compteurs de l'observateur."""
    observer = get_shadow_observer()
    observer.reset()
    return {"status": "reset_successful"}
