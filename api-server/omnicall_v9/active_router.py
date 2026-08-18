"""omnicall_v9/active_router.py — BLOC 9 : Routage actif OmniCall V9.

Ce module gère le branchement "actif" de V9 (rollout partiel).
Contrairement au Shadow Mode, ici V9 reçoit une partie ciblée du trafic
(beta stores + rollout déterministe) tout en conservant V8 comme fail-safe.

Important :
- BLOC 9 ne remplace pas encore les clients d'envoi (BLOC 10).
- Le traitement V9 est donc exécuté activement pour le trafic sélectionné,
  mais V8 reste le handler qui répond réellement tant que les clients V9 ne
  sont pas branchés.
- Si V9 échoue, aucune exception ne sort et le Circuit Breaker protège le flux.

FIX v20.3 :
- record_success() appelé sur le circuit breaker quand V9 traite avec succès
- Meilleure gestion des imports manquants
- Typage strict corrigé

VERSION: v24
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from omnicall_v9.circuit_breaker import v9_circuit
from omnicall_v9.flags.registry import (
    OMNICALL_V9_ENABLED,
    feature_flag,
    get_beta_store_ids,
    get_rollout_pct,
)
from omnicall_v9.normalizers.facebook import normalize_facebook_payload
from omnicall_v9.normalizers.instagram import normalize_instagram_payload
from omnicall_v9.normalizers.tiktok import normalize_tiktok_payload
from omnicall_v9.normalizers.whatsapp import normalize_whatsapp_payload
from omnicall_v9.observability.logger import log_pipeline_event
from omnicall_v9.observability.shadow_observer import get_shadow_observer
from omnicall_v9.pipeline.minimal import run_minimal_pipeline
from omnicall_v9.pipeline.safe_boundary import SafeProcessResult, safe_process_unified

logger = logging.getLogger("omnicall_v9.active_router")

T = TypeVar("T")

_NORMALIZERS: dict[str, Callable[[dict[str, object]], object]] = {
    "whatsapp": normalize_whatsapp_payload,
    "instagram": normalize_instagram_payload,
    "facebook": normalize_facebook_payload,
    "tiktok": normalize_tiktok_payload,
}


@dataclass(frozen=True)
class ActiveRouteDecision:
    active: bool
    reason: str
    rollout_pct: int
    bucket: int | None = None


def _compute_bucket(store_id: int) -> int:
    return int(hashlib.sha256(str(store_id).encode()).hexdigest(), 16) % 100


def get_active_route_decision(store_id: int | None) -> ActiveRouteDecision:
    """Retourne une décision stable de rollout actif pour un store.

    Priorité :
    1. flag global V9 actif
    2. circuit breaker fermé
    3. beta stores ciblés
    4. rollout déterministe par bucket store_id
    """
    rollout_pct = get_rollout_pct()

    if not feature_flag(OMNICALL_V9_ENABLED):
        return ActiveRouteDecision(active=False, reason="flag_disabled", rollout_pct=rollout_pct)

    if not v9_circuit.is_v9_safe():
        return ActiveRouteDecision(active=False, reason="circuit_open", rollout_pct=rollout_pct)

    beta_store_ids = get_beta_store_ids()
    if store_id is not None and store_id in beta_store_ids:
        return ActiveRouteDecision(active=True, reason="beta_store", rollout_pct=rollout_pct)

    if rollout_pct <= 0:
        return ActiveRouteDecision(active=False, reason="rollout_zero", rollout_pct=rollout_pct)

    if store_id is None:
        if rollout_pct >= 100:
            return ActiveRouteDecision(active=True, reason="global_rollout_100", rollout_pct=rollout_pct)
        return ActiveRouteDecision(active=False, reason="missing_store_id", rollout_pct=rollout_pct)

    bucket = _compute_bucket(store_id)
    if rollout_pct >= 100:
        return ActiveRouteDecision(active=True, reason="rollout_100", rollout_pct=rollout_pct, bucket=bucket)

    is_selected = bucket < rollout_pct
    return ActiveRouteDecision(
        active=is_selected,
        reason="rollout_bucket_in" if is_selected else "rollout_bucket_out",
        rollout_pct=rollout_pct,
        bucket=bucket,
    )


def route_to_v9_if_enabled[T](
    payload: dict[str, object],
    channel: str,
    store_id: int | None,
    v8_handler: Callable[..., T],
    *v8_args: object,
    decision: ActiveRouteDecision | None = None,
    **v8_kwargs: object,
) -> T:
    """Log la décision BLOC 9 puis exécute toujours le handler V8.

    Le fail-safe est volontaire : tant que BLOC 10 n'est pas livré,
    le résultat user-visible reste celui de V8.
    """
    route_decision = decision or get_active_route_decision(store_id)

    logger.info(
        "omnicall_v9.active_route.selected" if route_decision.active else "omnicall_v9.active_route.fallback",
        extra={
            "channel": channel,
            "store_id": store_id,
            "mode": "active_rollout" if route_decision.active else "v8_fallback",
            "reason": route_decision.reason,
            "rollout_pct": route_decision.rollout_pct,
            "bucket": route_decision.bucket,
        },
    )

    return v8_handler(*v8_args, **v8_kwargs)


def run_active_v9(
    payload: dict[str, object],
    channel: str,
    store_id: int | None = None,
) -> SafeProcessResult | None:
    """Exécute V9 pour le trafic sélectionné par BLOC 9.

    - Aucun throw externe.
    - Journalise le traitement actif.
    - Alimente les métriques d'observation.
    - Ouvre le circuit breaker uniquement sur erreurs système réelles.
    - FIX v20.3 : record_success() appelé pour permettre la sortie du HALF_OPEN.

    VERSION: v24
    """
    normalizer = _NORMALIZERS.get(channel)
    observer = get_shadow_observer()

    if normalizer is None:
        logger.warning(
            "omnicall_v9.active_route.unknown_channel",
            extra={"channel": channel, "store_id": store_id},
        )
        return None

    try:
        unified = normalizer(payload)
    except Exception as exc:
        v9_circuit.record_error()
        observer.record_normalize_error(channel, exc.__class__.__name__)
        logger.error(
            "omnicall_v9.active_route.normalize_failed",
            extra={
                "channel": channel,
                "store_id": store_id,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            },
        )
        return None

    result = safe_process_unified(
        unified,
        run_minimal_pipeline,
        log=logger,
    )

    route = getattr(result.processor_result, "route", None)
    handler_name = getattr(result.processor_result, "handler_name", None)

    if not result.accepted and result.error_type:
        v9_circuit.record_error()
    elif result.accepted:
        # FIX v20.3 : signal de succès pour la récupération HALF_OPEN
        v9_circuit.record_success()

    observer.record_shadow_processed(
        channel=channel,
        accepted=result.accepted,
        route=str(route) if route else None,
        reason=f"active:{result.reason}" if result.reason else "active",
        error_type=result.error_type,
    )

    log_pipeline_event(
        "omnicall_v9.active_route.processed",
        unified,
        channel=channel,
        store_id=store_id,
        v9_accepted=result.accepted,
        v9_reason=result.reason,
        v9_route=str(route) if route else None,
        v9_handler=handler_name,
        rollout_mode="active",
        duration_ms=result.duration_ms,
    )
    return result
