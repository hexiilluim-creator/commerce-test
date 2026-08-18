"""omnicall_v9/types/unified_message.py — Modèle canonique unifié OmniCall V9.

Ce dataclass est le contrat interne entre les normaliseurs de canaux et le pipeline.
Immuable, sans effet de bord, sans dépendance DB/réseau.

VERSION: v24
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any


class ChannelType(StrEnum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"
    UNKNOWN = "unknown"


class DirectionType(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    INTERACTIVE = "interactive"
    LOCATION = "location"
    STATUS = "status"
    UNKNOWN = "unknown"


class InteractiveReplyType(StrEnum):
    BUTTON = "button"
    LIST = "list"
    QUICK_REPLY = "quick_reply"


@dataclass(frozen=True)
class IdentityRef:
    """Référence d'identité pour expéditeur ou destinataire."""
    external_id: str | None = None
    phone: str | None = None
    username: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class MediaAttachment:
    """Pièce jointe média normalisée."""
    media_id: str | None = None
    mime_type: str | None = None
    url: str | None = None
    sha256: str | None = None
    caption: str | None = None


@dataclass(frozen=True)
class LocationPayload:
    """Localisation GPS normalisée."""
    latitude: float
    longitude: float
    name: str | None = None
    address: str | None = None


@dataclass(frozen=True)
class InteractivePayload:
    """Réponse interactive (bouton, liste, quick reply)."""
    reply_type: InteractiveReplyType
    reply_id: str | None = None
    title: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UnifiedMessage:
    """Message canonique unifié — contrat interne OmniCall V9.

    Ce modèle est produit par les normaliseurs de canal et consommé
    par le pipeline. Toute modification de ce schéma doit être
    rétrocompatible ou accompagnée d'une migration de version.
    """
    # Identifiants
    message_id: str
    channel: ChannelType
    direction: DirectionType
    message_kind: MessageKind

    # Temporel
    event_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Tenant
    store_id: int | None = None
    tenant_ref: str | None = None

    # Canal
    channel_account_id: str | None = None
    channel_message_id: str | None = None

    # Parties
    sender: IdentityRef = field(default_factory=IdentityRef)
    recipient: IdentityRef | None = None

    # Contenu
    text: str | None = None
    media: list[MediaAttachment] = field(default_factory=list)
    location: LocationPayload | None = None
    interactive: InteractivePayload | None = None

    # Observabilité
    raw_event: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Versioning du schéma
    schema_version: str = "v9.3"

    def has_text(self) -> bool:
        return bool(self.text and self.text.strip())

    def has_media(self) -> bool:
        return bool(self.media)

    def has_location(self) -> bool:
        return self.location is not None

    def has_interactive(self) -> bool:
        return self.interactive is not None

    def is_actionable(self) -> bool:
        """Retourne True si le message nécessite une réponse de l'agent."""
        return (
            self.direction == DirectionType.INBOUND
            and self.message_kind not in (MessageKind.STATUS, MessageKind.UNKNOWN)
        )

    def token_budget_estimate(self) -> int:
        """Estimation grossière du coût en tokens pour le LLM."""
        base = len(self.text or "") // 4
        media_cost = len(self.media) * 85
        return max(10, base + media_cost)
