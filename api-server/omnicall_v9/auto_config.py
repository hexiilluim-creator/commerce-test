"""omnicall_v9/auto_config.py — Fast-Track Plus : Auto-configuration.

Ajuste les paramètres de V9 en fonction de la charge système.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("omnicall_v9.auto_config")

def get_dynamic_rollout_limit() -> int:
    """Retourne une limite de rollout basée sur la charge (simulé).
    En prod, cela pourrait lire le CPU/RAM.
    """
    # Exemple : si une variable d'urgence est mise, on bride à 5%
    if os.environ.get("SYSTEM_LOAD_HIGH") == "1":
        logger.warning("High system load detected, capping V9 rollout to 5%")
        return 5
    return 100

def apply_load_balancing(current_pct: int) -> int:
    limit = get_dynamic_rollout_limit()
    return min(current_pct, limit)
