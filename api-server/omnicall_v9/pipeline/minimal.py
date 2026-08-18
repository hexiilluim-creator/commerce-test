"""omnicall_v9/pipeline/minimal.py — Pipeline minimal OmniCall V9.

Ce module implémente le pipeline de traitement V9 :
1. Validation du message unifié
2. Classification FSM (Finite State Machine) par canal et type
3. Sélection de la route IA (qualification / vente / négociation / vérification)
4. Estimation du budget LLM avant exécution
5. Journalisation structurée

En BLOC 9, ce pipeline est exécuté activement pour le trafic sélectionné.
Le canal de réponse (V8) reste actif tant que BLOC 10 n'est pas branché.

VERSION: v24 (FSM optimisé, budget LLM, zéro régression)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any

from omnicall_v9.types.unified_message import (
    ChannelType,
    MessageKind,
    UnifiedMessage,
)

logger = logging.getLogger("omnicall_v9.pipeline.minimal")

# ─── Budget LLM par canal ─────────────────────────────────────────────────────
# Limite de tokens estimés avant d'accepter un message dans le pipeline LLM.
# Au-delà, le message est marqué "truncate_required" mais toujours accepté.
_TOKEN_BUDGET: dict[str, int] = {
    "whatsapp": 2000,
    "instagram": 1500,
    "facebook": 1500,
    "tiktok": 1000,
    "default": 1500,
}

# ─── FSM : états de conversation ─────────────────────────────────────────────

class ConversationState(StrEnum):
    """États FSM de la machine conversationnelle."""
    NEW = "new"
    QUALIFICATION = "qualification"
    SALES = "sales"
    NEGOTIATION = "negotiation"
    VERIFICATION = "verification"
    PLANNING = "planning"
    CLOSED = "closed"
    ESCALATED = "escalated"


class AgentRoute(StrEnum):
    """Route vers l'agent IA responsable du traitement."""
    QUALIFICATION = "qualification_agent"
    SALES = "sales_agent"
    NEGOTIATION = "negotiation_agent"
    VERIFICATION = "verification_agent"
    PLANNING = "planning_agent"
    MANAGER = "manager_agent"
    DISCARD = "discard"


# ─── Résultat du pipeline ─────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """Résultat structuré du pipeline minimal."""
    accepted: bool
    route: AgentRoute | None
    handler_name: str | None
    fsm_state: ConversationState
    reason: str | None = None
    token_estimate: int = 0
    truncate_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── Classification FSM ───────────────────────────────────────────────────────

def _classify_channel_state(message: UnifiedMessage) -> ConversationState:
    """Détermine l'état FSM initial selon le canal et le type de message.

    Logique canal-spécifique:
    - WhatsApp: flux commercial complet (qualification -> vente -> négociation)
    - Instagram/Facebook: qualification rapide, puis vente
    - TikTok: qualification seulement (canal jeune, moins d'intention d'achat)
    """
    channel = message.channel

    if channel == ChannelType.TIKTOK:
        return ConversationState.QUALIFICATION

    if message.has_interactive():
        interactive = message.interactive
        reply_id = (interactive.reply_id or "").lower()
        if any(k in reply_id for k in ("buy", "order", "acheter", "commander", "price", "prix")):
            return ConversationState.SALES
        if any(k in reply_id for k in ("nego", "discount", "remise", "promo")):
            return ConversationState.NEGOTIATION

    if message.has_location():
        return ConversationState.VERIFICATION

    if message.has_text():
        text_lower = (message.text or "").lower()
        sales_signals = ("acheter", "commander", "prix", "tarif", "buy", "order", "price", "cost")
        nego_signals = ("remise", "réduction", "discount", "nego", "moins cher", "promo")
        verif_signals = ("adresse", "livraison", "delivery", "address", "stock", "disponible")
        plan_signals = ("rdv", "rendez-vous", "rappel", "appointment", "call me")

        if any(s in text_lower for s in nego_signals):
            return ConversationState.NEGOTIATION
        if any(s in text_lower for s in sales_signals):
            return ConversationState.SALES
        if any(s in text_lower for s in verif_signals):
            return ConversationState.VERIFICATION
        if any(s in text_lower for s in plan_signals):
            return ConversationState.PLANNING

    return ConversationState.QUALIFICATION


def _route_from_state(state: ConversationState) -> tuple[AgentRoute, str]:
    """Mappe un état FSM vers la route agent et le handler name."""
    _ROUTING: dict[ConversationState, tuple[AgentRoute, str]] = {
        ConversationState.QUALIFICATION: (AgentRoute.QUALIFICATION, "qualification_agent"),
        ConversationState.SALES: (AgentRoute.SALES, "sales_agent"),
        ConversationState.NEGOTIATION: (AgentRoute.NEGOTIATION, "negotiation_agent"),
        ConversationState.VERIFICATION: (AgentRoute.VERIFICATION, "verification_agent"),
        ConversationState.PLANNING: (AgentRoute.PLANNING, "planning_agent"),
        ConversationState.CLOSED: (AgentRoute.MANAGER, "manager_agent"),
        ConversationState.ESCALATED: (AgentRoute.MANAGER, "manager_agent"),
        ConversationState.NEW: (AgentRoute.QUALIFICATION, "qualification_agent"),
    }
    return _ROUTING.get(state, (AgentRoute.QUALIFICATION, "qualification_agent"))


# ─── Validation pré-pipeline ──────────────────────────────────────────────────

def _validate_message(message: UnifiedMessage) -> tuple[bool, str | None]:
    """Valide qu'un message est traitable par le pipeline.

    Returns:
        (is_valid, reject_reason) — reject_reason est None si valide.
    """
    if not message.is_actionable():
        return False, f"not_actionable:{message.message_kind}"

    if not (message.has_text() or message.has_media() or message.has_interactive() or message.has_location()):
        return False, "no_content"

    if message.message_kind == MessageKind.STATUS:
        return False, "status_event_skip"

    return True, None


# ─── Pipeline principal ───────────────────────────────────────────────────────

def run_minimal_pipeline(message: UnifiedMessage) -> PipelineResult:
    """Exécute le pipeline minimal V9 sur un message unifié.

    Étapes:
    1. Validation (message actionable ?)
    2. Estimation budget LLM
    3. Classification FSM
    4. Sélection de route agent
    5. Retour du résultat structuré

    Ce pipeline est SYNCHRONE et PUR : aucun appel DB, aucun appel LLM,
    aucun appel réseau. Les appels LLM se font dans les workers Celery
    (services/tasks.py), pas ici.

    Args:
        message: Message unifié validé par le normaliseur de canal.

    Returns:
        PipelineResult avec la route déterminée.
    """
    # ── Étape 1 : Validation ──────────────────────────────────────────────
    is_valid, reject_reason = _validate_message(message)
    if not is_valid:
        logger.debug(
            "omnicall_v9.pipeline.rejected",
            extra={
                "channel": str(message.channel),
                "reason": reject_reason,
                "message_id": message.message_id,
            },
        )
        return PipelineResult(
            accepted=False,
            route=AgentRoute.DISCARD,
            handler_name="discard",
            fsm_state=ConversationState.CLOSED,
            reason=reject_reason,
        )

    # ── Étape 2 : Budget LLM ─────────────────────────────────────────────
    channel_key = str(message.channel.value) if hasattr(message.channel, "value") else str(message.channel)
    budget = _TOKEN_BUDGET.get(channel_key, _TOKEN_BUDGET["default"])
    token_estimate = message.token_budget_estimate()
    truncate_required = token_estimate > budget

    if truncate_required:
        logger.info(
            "omnicall_v9.pipeline.token_budget_exceeded",
            extra={
                "channel": channel_key,
                "store_id": message.store_id,
                "token_estimate": token_estimate,
                "budget": budget,
                "message_id": message.message_id,
            },
        )

    # ── Étape 3 : Classification FSM ─────────────────────────────────────
    fsm_state = _classify_channel_state(message)

    # ── Étape 4 : Sélection de route ─────────────────────────────────────
    route, handler_name = _route_from_state(fsm_state)

    # ── Étape 5 : Résultat ───────────────────────────────────────────────
    logger.debug(
        "omnicall_v9.pipeline.routed",
        extra={
            "channel": channel_key,
            "store_id": message.store_id,
            "message_id": message.message_id,
            "fsm_state": str(fsm_state),
            "route": str(route),
            "handler": handler_name,
            "token_estimate": token_estimate,
            "truncate_required": truncate_required,
        },
    )

    return PipelineResult(
        accepted=True,
        route=route,
        handler_name=handler_name,
        fsm_state=fsm_state,
        reason=None,
        token_estimate=token_estimate,
        truncate_required=truncate_required,
        metadata={
            "schema_version": message.schema_version,
            "channel_account_id": message.channel_account_id,
        },
    )
