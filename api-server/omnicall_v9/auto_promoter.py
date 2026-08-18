"""omnicall_v9/auto_promoter.py — BLOC 9 Fast-Track : Promotion automatique.

Ce module analyse les métriques du Shadow Mode et propose (ou applique)
une augmentation du pourcentage de rollout si les seuils de confiance sont atteints.

Seuils de confiance par défaut :
- Taux d'acceptation > 99%
- Erreurs de normalisation = 0
- Volume minimum de messages > 100 par canal
"""
from __future__ import annotations

import logging
import os

from omnicall_v9.observability.shadow_observer import get_shadow_observer

logger = logging.getLogger("omnicall_v9.auto_promoter")

class AutoPromoter:
    def __init__(
        self,
        min_messages: int = 100,
        min_acceptance_rate: float = 99.0,
        max_normalize_errors: int = 0
    ):
        self.min_messages = min_messages
        self.min_acceptance_rate = min_acceptance_rate
        self.max_normalize_errors = max_normalize_errors
        self.observer = get_shadow_observer()

    def analyze_readiness(self) -> dict[str, object]:
        """Analyse si le système est prêt pour une augmentation du rollout."""
        report = self.observer.get_report()
        channels = report.get("channels", {})
        
        readiness = {}
        global_ready = True
        
        if not channels:
            return {"ready": False, "reason": "No traffic observed yet"}

        for channel, stats in channels.items():
            is_ready = (
                stats["total"] >= self.min_messages and
                stats["acceptance_rate_pct"] >= self.min_acceptance_rate and
                stats["normalize_errors"] <= self.max_normalize_errors
            )
            
            readiness[channel] = {
                "ready": is_ready,
                "total_messages": stats["total"],
                "acceptance_rate": stats["acceptance_rate_pct"],
                "errors": stats["normalize_errors"]
            }
            
            if not is_ready:
                global_ready = False

        return {
            "ready": global_ready,
            "channels": readiness,
            "current_rollout_pct": int(os.environ.get("OMNICALL_V9_ROLLOUT_PCT", "0")),
            "suggested_rollout_pct": self._suggest_next_step(global_ready)
        }

    def _suggest_next_step(self, is_ready: bool) -> int:
        current = int(os.environ.get("OMNICALL_V9_ROLLOUT_PCT", "0"))
        if not is_ready:
            return current
        
        # Escalade agressive mais contrôlée
        if current == 0: return 5
        if current == 5: return 20
        if current == 20: return 50
        if current == 50: return 100
        return current

def get_promotion_report() -> dict[str, object]:
    promoter = AutoPromoter()
    return promoter.analyze_readiness()
