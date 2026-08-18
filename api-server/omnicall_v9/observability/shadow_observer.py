"""omnicall_v9/observability/shadow_observer.py — BLOC 8 : Observation prod.

Ce module fournit des outils pour analyser les logs du Shadow Mode V9 :
- Compteurs d'événements (normalisations réussies/échouées, routes).
- Détection des erreurs de mapping.
- Rapport de santé du pipeline V9.

Utilisation :
    from omnicall_v9.observability.shadow_observer import ShadowObserver
    observer = ShadowObserver()
    observer.record_event("omnicall_v9.shadow.processed", channel="whatsapp", accepted=True)
    report = observer.get_report()
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("omnicall_v9.observer")


@dataclass
class ChannelStats:
    """Statistiques par canal."""
    total: int = 0
    accepted: int = 0
    rejected: int = 0
    normalize_errors: int = 0
    routes: dict = field(default_factory=lambda: defaultdict(int))
    error_types: dict = field(default_factory=lambda: defaultdict(int))
    last_event_at: datetime | None = None


class ShadowObserver:
    """Observateur thread-safe pour le Shadow Mode V9.

    Collecte les métriques en mémoire pour analyse rapide.
    En production, ces métriques doivent être exportées vers Prometheus/Grafana.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stats: dict[str, ChannelStats] = defaultdict(ChannelStats)
        self._started_at = datetime.now(UTC)
        self._total_events = 0

    def record_shadow_processed(
        self,
        channel: str,
        accepted: bool,
        route: str | None = None,
        reason: str | None = None,
        error_type: str | None = None,
    ) -> None:
        """Enregistre un événement de traitement Shadow V9."""
        with self._lock:
            stats = self._stats[channel]
            stats.total += 1
            self._total_events += 1
            stats.last_event_at = datetime.now(UTC)
            if accepted:
                stats.accepted += 1
                if route:
                    stats.routes[route] += 1
            else:
                stats.rejected += 1
                if error_type:
                    stats.error_types[error_type] += 1

    def record_normalize_error(self, channel: str, error_type: str) -> None:
        """Enregistre une erreur de normalisation."""
        with self._lock:
            stats = self._stats[channel]
            stats.normalize_errors += 1
            stats.error_types[f"normalize.{error_type}"] += 1
            self._total_events += 1

    def get_report(self) -> dict[str, object]:
        """Génère un rapport de santé du Shadow Mode V9."""
        with self._lock:
            uptime_seconds = (datetime.now(UTC) - self._started_at).total_seconds()
            channels_report = {}
            for channel, stats in self._stats.items():
                acceptance_rate = (
                    round(stats.accepted / stats.total * 100, 1)
                    if stats.total > 0 else 0.0
                )
                channels_report[channel] = {
                    "total": stats.total,
                    "accepted": stats.accepted,
                    "rejected": stats.rejected,
                    "normalize_errors": stats.normalize_errors,
                    "acceptance_rate_pct": acceptance_rate,
                    "routes": dict(stats.routes),
                    "error_types": dict(stats.error_types),
                    "last_event_at": stats.last_event_at.isoformat() if stats.last_event_at else None,
                }
            return {
                "shadow_mode": "active",
                "started_at": self._started_at.isoformat(),
                "uptime_seconds": round(uptime_seconds, 1),
                "total_events": self._total_events,
                "channels": channels_report,
            }

    def reset(self) -> None:
        """Remet à zéro les statistiques (pour les tests)."""
        with self._lock:
            self._stats.clear()
            self._total_events = 0
            self._started_at = datetime.now(UTC)


# Instance globale (singleton) pour l'application
_observer = ShadowObserver()


def get_shadow_observer() -> ShadowObserver:
    """Retourne l'instance globale de l'observateur."""
    return _observer
