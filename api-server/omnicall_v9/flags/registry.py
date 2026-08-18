"""omnicall_v9/flags/registry.py — Feature flags runtime pour OmniCall V9.

Stratégie :
- Les flags sont lus depuis les variables d'environnement au démarrage.
- OMNICALL_V9_SHADOW_MODE=1  -> V9 tourne en parallèle, V8 inchangé.
- OMNICALL_V9_ENABLED=1      -> V9 actif (post-shadow, rollout partiel).
- OMNICALL_V9_ROLLOUT_PCT=5  -> % de trafic routé vers V9 (0-100, défaut 0).
- OMNICALL_V9_BETA_STORES    -> liste de store_id séparés par virgule (ex: "1,2,3").
- OMNICALL_V9_DUAL_READ=1    -> lecture duale pour comparaison (futur).

Aucune modification de V8 n'est faite ici. Ce module est read-only pour les callers.

VERSION: v24 (logique dupliquée corrigée dans should_run_v9_shadow)
"""
from __future__ import annotations

import hashlib
import logging
import os

logger = logging.getLogger("omnicall_v9.flags")

# ─── Noms des flags (constantes stables) ──────────────────────────────────────
OMNICALL_V9_ENABLED = "omnicall_v9_enabled"
OMNICALL_V9_SHADOW_MODE = "omnicall_v9_shadow_mode"
OMNICALL_V9_DUAL_READ = "omnicall_v9_dual_read"
OMNICALL_V9_ROLLOUT_PCT = "omnicall_v9_rollout_pct"
OMNICALL_V9_BETA_STORES = "omnicall_v9_beta_stores"


# ─── Lecture des flags depuis l'environnement ─────────────────────────────────

def feature_flag(name: str) -> bool:
    """Retourne True si le flag booléen est activé (valeur '1' ou 'true' en env)."""
    env_key = name.upper()
    val = os.environ.get(env_key, "0").strip().lower()
    return val in ("1", "true", "yes", "on")


def get_rollout_pct() -> int:
    """Retourne le pourcentage de rollout (0-100)."""
    try:
        pct = int(os.environ.get("OMNICALL_V9_ROLLOUT_PCT", "0"))
        return max(0, min(100, pct))
    except (ValueError, TypeError):
        return 0


def get_beta_store_ids() -> frozenset[int]:
    """Retourne l'ensemble des store_id beta."""
    raw = os.environ.get("OMNICALL_V9_BETA_STORES", "").strip()
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return frozenset(ids)


# ─── Décision de routage V9 ───────────────────────────────────────────────────

def should_run_v9_shadow(store_id: int | None = None) -> bool:
    """Retourne True si le Shadow Mode V9 doit s'exécuter.

    FIX v20.3: Suppression de la vérification redondante du flag (était vérifié
    deux fois dans la version précédente, la deuxième étant toujours True
    si la première l'était déjà).
    """
    if not feature_flag(OMNICALL_V9_SHADOW_MODE):
        return False
    # Beta stores ont toujours le shadow mode activé si le flag global est ON
    if store_id is not None and store_id in get_beta_store_ids():
        return True
    # Pour les stores non-beta, le flag global suffit
    return True


def should_run_v9_active(store_id: int | None = None) -> bool:
    """Retourne True si V9 est activé en mode actif (rollout partiel)."""
    if not feature_flag(OMNICALL_V9_ENABLED):
        return False

    if store_id is not None and store_id in get_beta_store_ids():
        return True

    pct = get_rollout_pct()
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    if store_id is None:
        return False

    # Hachage déterministe pour un rollout stable par store
    bucket = int(hashlib.sha256(str(store_id).encode()).hexdigest(), 16) % 100
    return bucket < pct
