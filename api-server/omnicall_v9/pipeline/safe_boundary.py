"""omnicall_v9/pipeline/safe_boundary.py — Frontière de sécurité du pipeline V9.

Isole le pipeline de toute exception non gérée.
Garantit que le pipeline V9 ne bloque jamais le flux V8.

VERSION: v24
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from omnicall_v9.types.unified_message import UnifiedMessage

logger = logging.getLogger("omnicall_v9.safe_boundary")

# Timeout maximum pour l'exécution du pipeline (secondes)
PIPELINE_TIMEOUT_SECONDS: float = 8.0


@dataclass
class SafeProcessResult:
    """Résultat sécurisé du traitement pipeline V9."""
    accepted: bool
    reason: str | None = None
    error_type: str | None = None
    duration_ms: float = 0.0
    processor_result: Any = None


def safe_process_unified(
    message: UnifiedMessage,
    processor: Callable[[UnifiedMessage], Any],
    *,
    log: logging.Logger | None = None,
) -> SafeProcessResult:
    """Exécute processor(message) dans une frontière de sécurité totale.

    - Capture toute exception sans la propager.
    - Mesure le temps d'exécution.
    - Retourne un SafeProcessResult quel que soit le résultat.

    Args:
        message: Message unifié à traiter.
        processor: Fonction de traitement (run_minimal_pipeline, etc.)
        log: Logger optionnel (utilise le logger du module par défaut).

    Returns:
        SafeProcessResult avec le résultat ou l'erreur encapsulée.
    """
    _log = log or logger
    start = time.perf_counter()

    try:
        result = processor(message)
        duration_ms = (time.perf_counter() - start) * 1000

        accepted = getattr(result, "accepted", True)
        reason = getattr(result, "reason", None)

        return SafeProcessResult(
            accepted=accepted,
            reason=reason,
            duration_ms=round(duration_ms, 2),
            processor_result=result,
        )

    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        error_type = exc.__class__.__name__

        _log.error(
            "omnicall_v9.safe_boundary.pipeline_error",
            extra={
                "channel": str(message.channel),
                "store_id": message.store_id,
                "message_id": message.message_id,
                "error": str(exc),
                "error_type": error_type,
                "duration_ms": round(duration_ms, 2),
            },
            exc_info=False,
        )

        return SafeProcessResult(
            accepted=False,
            reason="pipeline_exception",
            error_type=error_type,
            duration_ms=round(duration_ms, 2),
            processor_result=None,
        )
