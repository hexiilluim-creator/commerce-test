"""services/fernet_rotation.py — Rotation multi-clé Fernet (HIGH-8 FIX).

Gère le chiffrement/déchiffrement des secrets sensibles des tenants
(tokens WhatsApp, clés paiement, etc.) avec support de la rotation de clés.

Fonctionnement:
  - FERNET_KEYS_JSON = '["nouvelle_cle=", "ancienne_cle="]'
    → MultiFernet : chiffre avec la 1ère clé, déchiffre en essayant toutes.
  - FERNET_KEYS_JSON vide → utilise ENCRYPTION_KEY seul (mode legacy / simple).

Utilisation via Settings:
    settings.encrypt("valeur_sensible")  → "token_chiffré"
    settings.decrypt("token_chiffré")   → "valeur_sensible"

NE PAS appeler get_fernet() au module level — appelé uniquement en lazy import
depuis config.Settings.{encrypt,decrypt,get_fernet} pour éviter les imports
circulaires (config.py → services → config.py).
"""
from __future__ import annotations

import json
import logging
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger(__name__)

_fernet_instance: Fernet | MultiFernet | None = None


def _build_fernet() -> Fernet | MultiFernet:
    """Construit l'instance Fernet depuis les variables d'environnement.

    Appelé une seule fois — résultat mis en cache dans _fernet_instance.
    """
    fernet_keys_json = os.environ.get("FERNET_KEYS_JSON", "").strip()
    encryption_key = os.environ.get("ENCRYPTION_KEY", "").strip()

    if not encryption_key:
        raise RuntimeError(
            "ENCRYPTION_KEY environment variable is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )

    if fernet_keys_json:
        try:
            raw_keys: list[str] = json.loads(fernet_keys_json)
            if not isinstance(raw_keys, list) or not raw_keys:
                raise ValueError("FERNET_KEYS_JSON must be a non-empty JSON array of Fernet key strings")
            fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in raw_keys]
            logger.info("fernet_rotation: MultiFernet with %d key(s)", len(fernets))
            return MultiFernet(fernets)
        except (json.JSONDecodeError, ValueError, Exception) as exc:
            raise RuntimeError(
                f"Invalid FERNET_KEYS_JSON: {exc}. "
                "Must be a JSON array of valid Fernet base64 keys, newest first."
            ) from exc

    # Fallback: single key (legacy / simple setup)
    try:
        fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        logger.debug("fernet_rotation: single-key Fernet (FERNET_KEYS_JSON not set)")
        return fernet
    except Exception as exc:
        raise RuntimeError(
            f"ENCRYPTION_KEY is not a valid Fernet key: {exc}. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        ) from exc


def get_fernet() -> Fernet | MultiFernet:
    """Retourne l'instance Fernet (ou MultiFernet) en cache.

    Thread-safe pour CPython (GIL). En multi-process uvicorn, chaque worker
    construit sa propre instance à partir des mêmes env vars.
    """
    global _fernet_instance
    if _fernet_instance is None:
        _fernet_instance = _build_fernet()
    return _fernet_instance


_CONTEXT_SEP = "\x00"


def encrypt(value: str, context: str | None = None) -> str:
    """Chiffre une chaîne avec la clé active (première de FERNET_KEYS_JSON).

    Args:
        value: Valeur en clair à chiffrer.
        context: AUDIT FIX (optionnel, rétrocompatible) — Fernet ne supporte
            pas nativement l'AAD (Additional Authenticated Data). Si fourni
            (ex: f"tenant:{store_id}:whatsapp_token"), ce contexte est lié
            cryptographiquement à la valeur : un ciphertext déplacé vers une
            autre ligne/tenant échouera au déchiffrement au lieu de se
            déchiffrer silencieusement avec le mauvais contexte. Omis par
            défaut pour ne pas casser les 30+ appels existants qui ne
            passent pas de contexte — c'est un renfort optionnel, pas encore
            appliqué partout (migration des appelants existants = chantier
            séparé, nécessite de re-chiffrer les valeurs déjà stockées).

    Returns:
        Token Fernet en base64 (str).

    Raises:
        RuntimeError: Si ENCRYPTION_KEY invalide ou manquant.
    """
    if not value:
        return value
    f = get_fernet()
    payload = f"{context}{_CONTEXT_SEP}{value}" if context else value
    return f.encrypt(payload.encode("utf-8")).decode("utf-8")


def decrypt(token: str, context: str | None = None) -> str:
    """Déchiffre un token Fernet. Essaie toutes les clés disponibles (rotation).

    Args:
        token: Token Fernet (base64 str) à déchiffrer.
        context: Doit correspondre exactement au contexte passé à encrypt().
            Si le token a été chiffré avec un contexte mais qu'on en fournit
            un différent (ou aucun) ici, ValueError — le déplacement d'un
            ciphertext vers une autre ligne/tenant est détecté au lieu de se
            déchiffrer silencieusement.

    Returns:
        Valeur déchiffrée (str).

    Raises:
        ValueError: Si le token est invalide, ne peut être déchiffré par
            aucune clé, ou si le contexte ne correspond pas.
        RuntimeError: Si ENCRYPTION_KEY invalide ou manquant.
    """
    if not token:
        return token
    f = get_fernet()
    try:
        raw = f.decrypt(token.encode("utf-8") if isinstance(token, str) else token).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Fernet decryption failed — token is invalid or was encrypted with an unknown key. "
            "If you recently rotated keys, ensure the old key is still present in FERNET_KEYS_JSON."
        ) from exc

    if _CONTEXT_SEP in raw:
        stored_context, _, plain = raw.partition(_CONTEXT_SEP)
        if context is None or stored_context != context:
            raise ValueError(
                "Fernet decryption failed — context mismatch (ciphertext may have been "
                "moved to a different row/tenant than it was encrypted for)."
            )
        return plain

    # Pas de contexte stocké (valeur chiffrée avant ce fix, ou sans contexte
    # fourni à l'encryption) : comportement legacy inchangé.
    return raw


def reset_cache() -> None:
    """Vide le cache de l'instance Fernet (utile pour les tests unitaires)."""
    global _fernet_instance
    _fernet_instance = None
