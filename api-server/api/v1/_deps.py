"""api/v1/_deps.py — Shared FastAPI dependencies and route-level helpers.

Consolidates helpers duplicated across route files:
  - get_store_id()  : reads current tenant from ContextVar (was _sid() in 4 files)
  - date_range()    : returns (start, end) datetime pair for a period in days

Import with:
    from api.v1._deps import get_store_id, date_range
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Request

from middleware.tenant import current_tenant_id


def get_store_id() -> int:
    """Return the current authenticated tenant's store_id.

    Reads from the ContextVar set by TenantMiddleware after JWT validation.
    Raises RuntimeError if called outside a request context (should never
    happen in production — TenantMiddleware enforces auth before routing).
    """
    sid = current_tenant_id.get()
    if sid is None:
        raise RuntimeError("get_store_id() called outside authenticated request context")
    return sid


def date_range(days: int) -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes for the last `days` days."""
    end = datetime.now(UTC)
    return end - timedelta(days=days), end


# ── RBAC helpers ──────────────────────────────────────────────────────────────

# Role hierarchy within a tenant (ascending privilege).
# - viewer      : read-only dashboards and reports
# - manager     : orders + products + customers; cannot change billing or team
# - admin       : full tenant access (default for store owner)
# - super_admin : platform-level, enforced at TenantMiddleware level
ROLE_LEVELS: dict[str, int] = {
    "viewer":      10,
    "manager":     20,
    "admin":       30,
    "super_admin": 99,
}


def require_role(*roles: str):
    """FastAPI dependency factory: require at least `min_role` to access a route.

    Usage::

        from api.v1._deps import require_role

        @router.delete("/{product_id}")
        async def delete_product(
            request: Request,
            _: None = Depends(require_role("admin")),
        ):
            ...

    Role hierarchy (ascending): viewer → manager → admin → super_admin

    The user role is read from request.state.jwt_payload["role"], which is
    populated by TenantMiddleware after JWT validation. No extra DB query needed.
    """
    from fastapi import Depends, HTTPException

    async def _check(request: Request) -> None:
        payload = getattr(request.state, "jwt_payload", {})
        user_role = payload.get("role", "viewer")
        user_level = ROLE_LEVELS.get(user_role, 0)
        required_level = min(ROLE_LEVELS.get(r, 99) for r in roles) if roles else 99
        if user_level < required_level:
            min_role = next((r for r, l in ROLE_LEVELS.items() if l == required_level), "admin")
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Role '{min_role}' ou supérieur requis. "
                    f"Votre rôle actuel : '{user_role}'."
                ),
            )

    return Depends(_check)


def require_feature(feature: str):
    """FastAPI dependency: 403 if the tenant's active plan doesn't include `feature`.

    AJOUT (audit) : ferme le gap où les routers Plan E/F (promotions,
    loyalty_ia, visual_builder, restocking, b2b_portal) étaient enregistrés
    et accessibles sans aucune vérification de plan — tout tenant, y compris
    gratuit, y avait accès complet.

    Usage (au niveau du router, pas par route, pour ne rien oublier) :
        router = APIRouter(prefix="/promotions", dependencies=[require_feature("promotions")])

    Fail-closed par construction : check_plan_access() de security_overlay.guard
    refuse l'accès si le snapshot de facturation est indisponible (pas de
    fallback "ouvert" en cas d'erreur Redis/DB).
    """
    from fastapi import Depends, HTTPException

    from api.v1._deps import get_store_id
    from security_overlay.guard import get_guard

    async def _check(store_id: int = Depends(get_store_id)) -> None:
        allowed = await get_guard().check_plan_access(store_id, feature)
        if not allowed:
            # AUDIT FIX (rapport utilisateur) : message simplifié, sans le slug
            # technique de la fonctionnalité (ex: "loyalty_ia") qu'un utilisateur
            # non-développeur ne comprend pas.
            raise HTTPException(
                status_code=403,
                detail="Vous n'êtes pas abonné à un plan qui inclut cette fonctionnalité. "
                       "Contactez-nous pour mettre à niveau votre abonnement.",
            )

    return Depends(_check)
