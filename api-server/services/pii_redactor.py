"""services/pii_redactor.py — Redacteur PII pour conformité RGPD.

Référencé dans main.py — requis en production.
Masque les données personnelles dans les logs structlog.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Patterns PII à masquer
# P0-FIX (audit): Reordered patterns to prioritize [CARD] over [PHONE].
# Previously, a 16-digit card number was matched by the broad phone regex
# and masked as [PHONE] [PHONE], breaking security audit assertions.
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Numéros de carte bancaire (4 groupes de 4 chiffres) — MUST run before PHONE
    (re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"), "[CARD]"),
    # Emails
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    # Numéros de téléphone tunisiens et internationaux
    (re.compile(r"\b(?:\+216|00216|216)?[2-9]\d{7}\b"), "[PHONE]"),
    (re.compile(r"\b\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b"), "[PHONE]"),
    # CIN tunisien (8 chiffres)
    (re.compile(r"\b\d{8}\b"), "[CIN]"),
]


def _redact_string(value: str) -> str:
    """Applique tous les patterns de masquage sur une chaîne."""
    for pattern, replacement in _PII_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _redact_recursive(obj):
    """Redact PII récursivement dans des structures dict/list/str."""
    if isinstance(obj, str):
        return _redact_string(obj)
    elif isinstance(obj, dict):
        return {k: _redact_recursive(v) for k, v in obj.items()}
    elif isinstance(obj, list | tuple):
        return type(obj)(_redact_recursive(item) for item in obj)
    return obj


class PIIRedactorFilter(logging.Filter):
    """Filtre logging qui masque les PII dans tous les messages de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Masquer le message principal
        if isinstance(record.msg, str):
            record.msg = _redact_string(record.msg)
        # Masquer les arguments
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact_recursive(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_redact_recursive(a) for a in record.args)
        return True


def install_pii_redactor() -> None:
    """Installe le filtre PII sur le logger racine."""
    root_logger = logging.getLogger()
    # Éviter les doublons
    for f in root_logger.filters:
        if isinstance(f, PIIRedactorFilter):
            logger.debug("PII redactor already installed")
            return
    root_logger.addFilter(PIIRedactorFilter())
    logger.info("PII redactor installed — customer PII will be masked in logs")
