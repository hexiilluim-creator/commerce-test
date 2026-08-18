"""omnicall_v9/senders/base.py — Interface d'envoi unifiée OmniCall V9 (BLOC 10).

BLOC 10 : branchement des clients d'envoi V9.
Remplace les appels directs V8 (WhatsAppClient.send_text, etc.)
par une interface canal-agnostique qui passe par le pipeline V9.

Chaque sender implémente :
  async def send(reply: AgentReply) -> SendResult

AgentReply est le contrat de sortie du pipeline V9 vers les canaux.
SendResult encapsule le succès/échec sans jamais lever d'exception.

VERSION: v25 (BLOC 10 — premier branchement envoi V9)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any

from omnicall_v9.types.unified_message import ChannelType, UnifiedMessage

logger = logging.getLogger("omnicall_v9.senders")


# ── Contrat de réponse agent → canal ─────────────────────────────────────────

class ReplyKind(StrEnum):
    TEXT       = "text"
    TEMPLATE   = "template"
    INTERACTIVE = "interactive"
    IMAGE      = "image"
    AUDIO      = "audio"


@dataclass
class AgentReply:
    """Réponse structurée produite par un agent V9, destinée à être envoyée.

    Canal-agnostique : le sender adapte ce contrat au format attendu
    par l'API destination (Meta Graph, Instagram Graph, etc.).
    """
    # Destinataire
    recipient_id: str          # phone (WA), instagram_id, page_scoped_id, etc.
    channel: ChannelType

    # Contenu
    kind: ReplyKind = ReplyKind.TEXT
    text: str | None = None

    # Template (WA uniquement pour l'instant)
    template_name: str | None = None
    template_language: str = "fr"
    template_components: list[dict[str, Any]] = field(default_factory=list)

    # Interactif (boutons, listes)
    interactive_type: str | None = None       # "button" | "list"
    interactive_body: str | None = None
    interactive_buttons: list[dict] = field(default_factory=list)

    # Médias
    media_url: str | None = None
    media_caption: str | None = None

    # Métadonnées
    store_id: int | None = None
    trace_id: str | None = None
    in_reply_to: str | None = None            # message_id d'origine


@dataclass
class SendResult:
    """Résultat d'un envoi de réponse."""
    success: bool
    channel: ChannelType
    recipient_id: str
    provider_message_id: str | None = None    # WA wamid, IG msg id, etc.
    error: str | None = None
    latency_ms: float = 0.0

    def __bool__(self) -> bool:
        return self.success


# ── Interface sender ──────────────────────────────────────────────────────────

class BaseSender:
    """Interface abstraite pour tous les senders V9."""

    channel: ChannelType = ChannelType.UNKNOWN

    async def send(self, reply: AgentReply) -> SendResult:
        raise NotImplementedError

    def can_handle(self, channel: ChannelType) -> bool:
        return channel == self.channel


# ── Registry senders ─────────────────────────────────────────────────────────

_SENDER_REGISTRY: dict[ChannelType, BaseSender] = {}


def register_sender(sender: BaseSender) -> None:
    _SENDER_REGISTRY[sender.channel] = sender
    logger.debug("omnicall_v9.senders.registered channel=%s", sender.channel)


def get_sender(channel: ChannelType) -> BaseSender | None:
    return _SENDER_REGISTRY.get(channel)
