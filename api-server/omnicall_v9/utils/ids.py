"""omnicall_v9/utils/ids.py — Générateurs d'identifiants stables pour OmniCall V9.

Ces helpers sont purs : sans DB, sans réseau, sans état global.
VERSION: v24
"""
from __future__ import annotations

import hashlib
import time
import uuid


def build_message_fingerprint(
    *,
    channel: str,
    external_message_id: str,
    sender_id: str,
    extra: str = "",
) -> str:
    """Construit un fingerprint stable pour un message sans message_id fourni.

    Le fingerprint est déterministe pour les mêmes entrées afin d'assurer
    l'idempotence de traitement, mais inclut un suffixe temporel court
    pour éviter les collisions sur des messages distincts avec le même contenu.

    Args:
        channel: Nom du canal (whatsapp, instagram, etc.)
        external_message_id: ID fourni par la plateforme (peut être "missing")
        sender_id: ID expéditeur (peut être "unknown")
        extra: Données additionnelles pour différencier (timestamp, body hash, etc.)

    Returns:
        Fingerprint hex de 40 caractères, préfixé par le canal.
    """
    raw = f"{channel}:{external_message_id}:{sender_id}:{extra}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"{channel[:3]}-{digest}"


def build_trace_id() -> str:
    """Génère un trace_id unique pour l'observabilité."""
    return f"oc9-{uuid.uuid4().hex[:16]}"


def build_idempotency_key(
    *,
    channel: str,
    store_id: int | None,
    message_id: str,
) -> str:
    """Clé Redis pour la déduplication idempotente des messages entrants.

    Format: omnicall:dedup:{channel}:{store_id}:{message_id}
    """
    sid = str(store_id) if store_id is not None else "none"
    return f"omnicall:dedup:{channel}:{sid}:{message_id}"
