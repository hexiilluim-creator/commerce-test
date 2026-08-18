"""security_overlay/guard.py — Garde de sécurité des endpoints."""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("security.guard")

try:
    from security_overlay.billing_overlay import get_billing_snapshot
except Exception:  # pragma: no cover - exercised through fail-closed paths
    async def get_billing_snapshot(store_id: int):  # type: ignore[no-redef]
        raise RuntimeError("billing snapshot provider unavailable")

try:
    from services.ai_guardrails import check_tenant_credit, deduct_tenant_credit, get_tenant_credit_stats
except Exception:  # pragma: no cover - exercised through fail-open/fail-closed paths
    async def check_tenant_credit(store_id: int, cost: int):  # type: ignore[no-redef]
        raise RuntimeError("credit checker unavailable")

    async def deduct_tenant_credit(store_id: int, cost: int):  # type: ignore[no-redef]
        raise RuntimeError("credit deductor unavailable")

    async def get_tenant_credit_stats(store_id: int):  # type: ignore[no-redef]
        raise RuntimeError("credit stats unavailable")


_SNAPSHOT_CACHE: dict[int, tuple[Any, float]] = {}
_CACHE_TTL = 300.0
_CACHE_MAX_SIZE = 2048

# P1.12-FIX (audit externe, juillet 2026) : compteur local mémoire pour
# plafonner check_credit en mode fail-open, comme documenté dans le TODO
# d'origine. Sans lui, une panne Redis/DB prolongée autorisait un volume
# illimité de requêtes IA sans aucun plafond pour un tenant donné. Ce n'est
# PAS un rate-limit général (distributed_rate_limit.py s'en charge déjà) —
# uniquement un filet de sécurité sur le crédit IA pendant une panne.
_FAILOPEN_WINDOW_SECONDS = 60.0
_FAILOPEN_MAX_PER_WINDOW = 20
_failopen_counters: dict[int, list[float]] = {}


def _failopen_allow(store_id: int) -> bool:
    """True si le tenant reste sous le plafond de secours local pour la
    fenêtre glissante en cours ; False si le plafond est dépassé (la requête
    doit alors être refusée, même en mode fail-open)."""
    now = time.monotonic()
    window_start = now - _FAILOPEN_WINDOW_SECONDS
    hits = [t for t in _failopen_counters.get(store_id, []) if t > window_start]
    if len(hits) >= _FAILOPEN_MAX_PER_WINDOW:
        _failopen_counters[store_id] = hits
        return False
    hits.append(now)
    _failopen_counters[store_id] = hits
    # Éviter une fuite mémoire non bornée si beaucoup de tenants sont actifs
    # pendant une panne prolongée.
    if len(_failopen_counters) > _CACHE_MAX_SIZE:
        stale = [sid for sid, ts in _failopen_counters.items() if not ts or ts[-1] <= window_start]
        for sid in stale[: len(stale) // 2 or 1]:
            _failopen_counters.pop(sid, None)
    return True


def _cache_get(store_id: int) -> Any | None:
    entry = _SNAPSHOT_CACHE.get(store_id)
    if entry is None:
        return None
    snapshot, expiry = entry
    if time.monotonic() > expiry:
        _SNAPSHOT_CACHE.pop(store_id, None)
        return None
    return snapshot



def _cache_set(store_id: int, snapshot: Any) -> None:
    if len(_SNAPSHOT_CACHE) >= _CACHE_MAX_SIZE:
        oldest = sorted(_SNAPSHOT_CACHE.items(), key=lambda x: x[1][1])
        eviction_count = max(1, _CACHE_MAX_SIZE // 10)
        for sid, _ in oldest[:eviction_count]:
            _SNAPSHOT_CACHE.pop(sid, None)
    _SNAPSHOT_CACHE[store_id] = (snapshot, time.monotonic() + _CACHE_TTL)


class SecurityGuard:
    """Garde de sécurité tenant-aware pour les features et les crédits IA."""

    async def check_plan_access(self, store_id: int, feature: str) -> bool:
        try:
            snapshot = await get_billing_snapshot(store_id)
            _cache_set(store_id, snapshot)
            result = snapshot.has_feature(feature)
            logger.debug(
                "check_plan_access store_id=%d feature=%s plan=%s result=%s",
                store_id, feature, snapshot.plan_code, result,
            )
            return result
        except Exception as exc:
            cached = _cache_get(store_id)
            if cached is not None:
                result = cached.has_feature(feature)
                logger.warning(
                    "check_plan_access using stale cache store_id=%d feature=%s plan=%s result=%s error=%s",
                    store_id, feature, cached.plan_code, result, exc,
                )
                return result
            logger.error(
                "check_plan_access FAIL-CLOSED store_id=%d feature=%s — no cache available, access denied. Error: %s",
                store_id, feature, exc,
            )
            return False

    async def check_feature_or_403(self, store_id: int, feature: str) -> None:
        from fastapi import HTTPException

        try:
            snapshot = await get_billing_snapshot(store_id)
            _cache_set(store_id, snapshot)
        except Exception as exc:
            cached = _cache_get(store_id)
            if cached is not None:
                snapshot = cached
                logger.warning(
                    "check_feature_or_403 using stale cache store_id=%d feature=%s error=%s",
                    store_id, feature, exc,
                )
            else:
                logger.error(
                    "check_feature_or_403 FAIL-CLOSED store_id=%d feature=%s error=%s",
                    store_id, feature, exc,
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "billing_service_unavailable",
                        "message": "Impossible de vérifier les droits du plan. Réessayez dans quelques instants.",
                    },
                )

        if not snapshot.has_feature(feature):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "feature_not_in_plan",
                    "feature": feature,
                    "current_plan": snapshot.plan_code,
                    "current_plan_label": snapshot.plan_label,
                    "upgrade_required": True,
                },
            )

    async def check_credit(self, store_id: int, action: str = "generic", cost: int = 1) -> bool:
        try:
            ok = await check_tenant_credit(store_id, cost)
            if not ok:
                logger.info(
                    "check_credit DENIED store_id=%d action=%s cost=%d",
                    store_id, action, cost,
                )
            return ok
        except Exception as exc:
            # FAIL-OPEN DOCUMENTÉ (audit V28), PLAFONNÉ (P1.12-FIX) :
            # en cas d'indisponibilité Redis/DB, la requête est autorisée
            # pour préserver l'UX, mais uniquement jusqu'à
            # _FAILOPEN_MAX_PER_WINDOW requêtes par tenant sur une fenêtre
            # glissante de _FAILOPEN_WINDOW_SECONDS — au-delà, refus même
            # en mode dégradé (mitigation du risque de surconsommation
            # illimitée pendant une panne prolongée).
            allowed = _failopen_allow(store_id)
            logger.warning(
                "check_credit error store_id=%d action=%s — fail-open %s (soft limit): %s",
                store_id, action, "ALLOWED" if allowed else "CAPPED-DENIED", exc,
            )
            return allowed

    async def deduct_credit(self, store_id: int, action: str = "generic", cost: int = 1) -> None:
        try:
            await deduct_tenant_credit(store_id, cost)
        except Exception as exc:
            logger.warning(
                "deduct_credit error store_id=%d action=%s cost=%d: %s",
                store_id, action, cost, exc,
            )

    async def dump_stats(self, store_id: int) -> dict:
        try:
            snapshot = await get_billing_snapshot(store_id)
            _cache_set(store_id, snapshot)
            usage = await get_tenant_credit_stats(store_id)
            return {
                "plan_code": snapshot.plan_code,
                "plan_label": snapshot.plan_label,
                "is_paid": snapshot.is_paid,
                "is_active": snapshot.is_active,
                "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
                "features": sorted(snapshot.features),
                "ai_credits": usage,
            }
        except Exception as exc:
            logger.error("dump_stats error store_id=%d: %s", store_id, exc)
            return {"error": str(exc)}


_guard_instance: SecurityGuard | None = None


def get_guard() -> SecurityGuard:
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = SecurityGuard()
    return _guard_instance
