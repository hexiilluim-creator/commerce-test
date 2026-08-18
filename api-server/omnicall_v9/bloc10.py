"""omnicall_v9/bloc10.py — BLOC 10 : Dispatcher V9 complet (remplace V8).

BLOC 10 est le point de bascule final entre V8 et V9.
Il branche les agents V9 sur les clients d'envoi, remplaçant ainsi
la chaîne V8 (ai_agent → WhatsAppClient) par la chaîne V9 :

    UnifiedMessage
        → pipeline/minimal.py       (classification FSM + route agent)
        → agents V9                  (LLM call avec contexte enrichi)
        → senders/whatsapp|social    (envoi via API canal)
        → SendResult                 (succès/échec loggué)

Sécurité :
  - Fail-safe : si le dispatcher V9 échoue, le flag V9 est désactivé pour
    ce message et V8 prend le relais (zéro régression).
  - Circuit Breaker mis à jour selon le résultat.
  - Budget guardrail : déduction crédit IA avant appel LLM.

Feature flags (variables d'environnement) :
  OMNICALL_V9_ENABLED=1           → V9 actif (remplace V8 pour le trafic routé)
  OMNICALL_V9_ROLLOUT_PCT=100     → 100% du trafic vers V9
  OMNICALL_V9_BETA_STORES=1,2,3   → beta stores forcés vers V9

VERSION: v25 (BLOC 10 — premier branchement complet)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import omnicall_v9.senders.social  # noqa: F401

# Import des senders pour les enregistrer dans le registre
import omnicall_v9.senders.whatsapp  # noqa: F401
from omnicall_v9.active_router import get_active_route_decision, run_active_v9
from omnicall_v9.circuit_breaker import v9_circuit
from omnicall_v9.flags.registry import OMNICALL_V9_ENABLED, feature_flag, get_beta_store_ids, get_rollout_pct
from omnicall_v9.pipeline.minimal import AgentRoute, PipelineResult, run_minimal_pipeline
from omnicall_v9.pipeline.safe_boundary import safe_process_unified
from omnicall_v9.senders.base import AgentReply, ReplyKind, SendResult, get_sender
from omnicall_v9.types.unified_message import ChannelType, UnifiedMessage

logger = logging.getLogger("omnicall_v9.bloc10")


# ── Résultat du dispatcher ────────────────────────────────────────────────────

@dataclass
class DispatchResult:
    """Résultat complet du dispatcher BLOC 10."""
    dispatched_by_v9: bool          # True si V9 a traité ET envoyé
    send_result: SendResult | None  # Résultat d'envoi (None si V8 fallback)
    pipeline_result: PipelineResult | None = None
    v8_fallback_reason: str | None = None
    latency_ms: float = 0.0

    @property
    def success(self) -> bool:
        if not self.dispatched_by_v9:
            return False  # Fallback V8, pas d'info ici
        return bool(self.send_result and self.send_result.success)


# ── Agents V9 ─────────────────────────────────────────────────────────────────
# Chaque route du pipeline V9 est mappée vers un handler async.
# Ces handlers appellent le LLM via llm_gateway et retournent du texte.

async def _call_qualification_agent(
    message: UnifiedMessage,
    db: Any,
    store: Any,
    customer: Any,
) -> str:
    """Agent de qualification V9 — détecte l'intention et engage le client."""
    from services.llm_gateway import chat

    system = (
        f"Tu es un assistant commercial pour la boutique '{getattr(store, 'name', 'AutoCommerce')}'.\n"
        "Ton rôle : comprendre le besoin du client et l'orienter vers le bon produit ou service.\n"
        "Réponds en {lang}, de façon naturelle, courte (2-3 phrases max).\n"
        "Ne propose pas de prix sans avoir identifié le besoin."
    ).format(lang="français ou la langue du client")

    user_text = message.text or ""
    completion = await chat(
        messages=[{"role": "user", "content": user_text}],
        system=system,
        agent_name="v9.qualification",
        tenant_id=message.store_id,
        max_tokens=200,
        temperature=0.6,
        channel=str(message.channel.value),
    )
    return completion.choices[0].message.content.strip()


async def _call_sales_agent(
    message: UnifiedMessage,
    db: Any,
    store: Any,
    customer: Any,
) -> str:
    """Agent de vente V9 — présente les produits, génère des liens de paiement."""
    from services.llm_gateway import chat

    # Récupérer quelques produits en stock pour le contexte
    product_context = ""
    try:
        from sqlalchemy import select

        from models.database import Product
        result = await db.execute(
            select(Product)
            .where(Product.store_id == store.id, Product.is_active, Product.stock_qty > 0)
            .order_by(Product.updated_at.desc())
            .limit(5)
        )
        products = result.scalars().all()
        if products:
            lines = [f"- {p.name} : {p.price:.3f} DT (stock: {p.stock_qty})" for p in products]
            product_context = "Produits disponibles :\n" + "\n".join(lines)
    except Exception as exc:
        logger.debug("v9.sales_agent product fetch failed: %s", exc)

    system = (
        f"Tu es un vendeur expert pour '{getattr(store, 'name', 'AutoCommerce')}'.\n"
        f"{product_context}\n"
        "Présente les produits pertinents, donne les prix, et propose de commander.\n"
        "Sois enthousiaste mais honnête. 3 phrases max."
    )

    completion = await chat(
        messages=[{"role": "user", "content": message.text or ""}],
        system=system,
        agent_name="v9.sales",
        tenant_id=message.store_id,
        max_tokens=300,
        temperature=0.5,
        channel=str(message.channel.value),
    )
    return completion.choices[0].message.content.strip()


async def _call_negotiation_agent(
    message: UnifiedMessage,
    db: Any,
    store: Any,
    customer: Any,
) -> str:
    """Agent de négociation V9 — gère les demandes de remise avec les règles du store."""
    from services.llm_gateway import chat

    max_discount = getattr(store, "max_discount_pct", 10) or 10

    system = (
        f"Tu gères les négociations pour '{getattr(store, 'name', 'AutoCommerce')}'.\n"
        f"Tu peux accorder jusqu'à {max_discount}% de réduction maximum.\n"
        "Si la demande est raisonnable, propose une remise. Sinon, explique poliment le prix.\n"
        "2 phrases max."
    )

    completion = await chat(
        messages=[{"role": "user", "content": message.text or ""}],
        system=system,
        agent_name="v9.negotiation",
        tenant_id=message.store_id,
        max_tokens=150,
        temperature=0.4,
        channel=str(message.channel.value),
    )
    return completion.choices[0].message.content.strip()


async def _call_verification_agent(
    message: UnifiedMessage,
    db: Any,
    store: Any,
    customer: Any,
) -> str:
    """Agent de vérification V9 — confirme commande, adresse, stock."""
    from services.llm_gateway import chat

    system = (
        f"Tu confirmes les détails de commande pour '{getattr(store, 'name', 'AutoCommerce')}'.\n"
        "Demande l'adresse de livraison si elle manque. Confirme le produit et le prix.\n"
        "Sois précis et rassurant. 2-3 phrases."
    )

    completion = await chat(
        messages=[{"role": "user", "content": message.text or ""}],
        system=system,
        agent_name="v9.verification",
        tenant_id=message.store_id,
        max_tokens=200,
        temperature=0.3,
        channel=str(message.channel.value),
    )
    return completion.choices[0].message.content.strip()


async def _call_planning_agent(
    message: UnifiedMessage,
    db: Any,
    store: Any,
    customer: Any,
) -> str:
    """Agent de planification V9 — gère les demandes de RDV et rappels."""
    from services.llm_gateway import chat

    system = (
        f"Tu gères les rendez-vous pour '{getattr(store, 'name', 'AutoCommerce')}'.\n"
        "Propose des créneaux disponibles. Demande le nom et le numéro si inconnus.\n"
        "2 phrases max."
    )

    completion = await chat(
        messages=[{"role": "user", "content": message.text or ""}],
        system=system,
        agent_name="v9.planning",
        tenant_id=message.store_id,
        max_tokens=150,
        temperature=0.5,
        channel=str(message.channel.value),
    )
    return completion.choices[0].message.content.strip()


async def _call_manager_agent(
    message: UnifiedMessage,
    db: Any,
    store: Any,
    customer: Any,
) -> str:
    """Agent manager V9 — escalade, clôture, situations complexes."""
    from services.llm_gateway import chat

    system = (
        f"Tu es le responsable de '{getattr(store, 'name', 'AutoCommerce')}'.\n"
        "Gère les situations sensibles avec empathie. Si besoin, propose de rappeler le client.\n"
        "2-3 phrases."
    )

    completion = await chat(
        messages=[{"role": "user", "content": message.text or ""}],
        system=system,
        agent_name="v9.manager",
        tenant_id=message.store_id,
        max_tokens=200,
        temperature=0.6,
        channel=str(message.channel.value),
    )
    return completion.choices[0].message.content.strip()


# Mapping route → nom de fonction handler (résolution tardive, voir usage
# ci-dessous dans dispatch_v9).
#
# AUDIT FIX : ce dict référençait directement les objets fonction
# (`_call_qualification_agent`, etc.) capturés au chargement du module. Un
# `unittest.mock.patch("omnicall_v9.bloc10._call_qualification_agent", ...)`
# ne changeait donc RIEN à ce que dispatch_v9 appelait réellement : le dict
# gardait la référence originale. Résultat observé en audit : le handler réel
# tentait un vrai appel LLM (aucune clé API en test) et levait
# AllProvidersFailedError, donc dispatched_by_v9 restait toujours False même
# dans le test "full_success". Fix : stocker les noms et résoudre via
# globals() à l'appel, pour que le patch du nom de module s'applique bien.
_AGENT_HANDLER_NAMES = {
    AgentRoute.QUALIFICATION: "_call_qualification_agent",
    AgentRoute.SALES:         "_call_sales_agent",
    AgentRoute.NEGOTIATION:   "_call_negotiation_agent",
    AgentRoute.VERIFICATION:  "_call_verification_agent",
    AgentRoute.PLANNING:      "_call_planning_agent",
    AgentRoute.MANAGER:       "_call_manager_agent",
}


# ── Guardrail crédits IA ──────────────────────────────────────────────────────

async def _check_and_deduct_credits(store_id: int, cost: int = 1) -> bool:
    """Vérifie et déduit les crédits IA. Retourne False si quota épuisé."""
    try:
        from services.ai_guardrails import check_tenant_credit, deduct_tenant_credit
        if not await check_tenant_credit(store_id, cost):
            logger.warning("omnicall_v9.bloc10.credit_exhausted store_id=%s", store_id)
            return False
        await deduct_tenant_credit(store_id, cost)
        return True
    except Exception as exc:
        logger.warning("omnicall_v9.bloc10.credit_check_failed store_id=%s error=%s", store_id, exc)
        return True  # Fail-open sur le check crédit pour ne pas bloquer le client


# ── Dispatcher principal ──────────────────────────────────────────────────────

async def dispatch_v9(
    unified_message: UnifiedMessage,
    *,
    db: Any,
    store: Any,
    customer: Any | None = None,
) -> DispatchResult:
    """Point d'entrée BLOC 10 — dispatche un message V9 de bout en bout.

    Flux :
      1. Vérification feature flag + circuit breaker
      2. Pipeline minimal (classification FSM, route agent)
      3. Guardrail crédits IA
      4. Appel agent LLM (selon route)
      5. Construction AgentReply
      6. Envoi via sender canal
      7. Mise à jour circuit breaker + métriques

    Args:
        unified_message : Message normalisé V9.
        db              : Session SQLAlchemy async.
        store           : Store ORM (tenant courant).
        customer        : Customer ORM (optionnel, enrichit le contexte agent).

    Returns:
        DispatchResult — jamais de throw externe.
    """
    start = time.perf_counter()
    store_id = unified_message.store_id

    # ── 1. Feature flag + circuit breaker ────────────────────────────────────
    if not feature_flag(OMNICALL_V9_ENABLED):
        return DispatchResult(
            dispatched_by_v9=False,
            send_result=None,
            v8_fallback_reason="flag_disabled",
        )

    if not v9_circuit.is_v9_safe():
        return DispatchResult(
            dispatched_by_v9=False,
            send_result=None,
            v8_fallback_reason="circuit_open",
        )

    # ── 2. Pipeline minimal (synchrone, pur) ──────────────────────────────────
    safe_result = safe_process_unified(unified_message, run_minimal_pipeline)

    if not safe_result.accepted:
        return DispatchResult(
            dispatched_by_v9=False,
            send_result=None,
            v8_fallback_reason=f"pipeline_rejected:{safe_result.reason}",
        )

    pipeline: PipelineResult = safe_result.processor_result

    if pipeline.route == AgentRoute.DISCARD:
        logger.debug("omnicall_v9.bloc10.discard store_id=%s reason=%s", store_id, pipeline.reason)
        return DispatchResult(
            dispatched_by_v9=True,  # Volontairement discard — pas de fallback V8
            send_result=None,
            pipeline_result=pipeline,
        )

    # ── 3. Guardrail crédits ─────────────────────────────────────────────────
    if store_id and not await _check_and_deduct_credits(store_id):
        return DispatchResult(
            dispatched_by_v9=False,
            send_result=None,
            v8_fallback_reason="credits_exhausted",
        )

    # ── 4. Appel agent LLM ───────────────────────────────────────────────────
    handler_name = _AGENT_HANDLER_NAMES.get(pipeline.route)
    handler = globals().get(handler_name) if handler_name else None
    if not handler:
        logger.error("omnicall_v9.bloc10.no_handler route=%s", pipeline.route)
        v9_circuit.record_error()
        return DispatchResult(
            dispatched_by_v9=False,
            send_result=None,
            v8_fallback_reason=f"no_handler:{pipeline.route}",
        )

    try:
        reply_text = await handler(unified_message, db, store, customer)
    except Exception as exc:
        logger.error("omnicall_v9.bloc10.agent_failed route=%s error=%s", pipeline.route, exc)
        v9_circuit.record_error()
        return DispatchResult(
            dispatched_by_v9=False,
            send_result=None,
            pipeline_result=pipeline,
            v8_fallback_reason=f"agent_exception:{exc.__class__.__name__}",
        )

    # ── 5. Construction AgentReply ────────────────────────────────────────────
    # Récupérer le sender_id (phone ou identifiant canal du client)
    sender_id = unified_message.sender.phone or unified_message.sender.external_id or ""

    agent_reply = AgentReply(
        recipient_id=sender_id,
        channel=unified_message.channel,
        kind=ReplyKind.TEXT,
        text=reply_text,
        store_id=store_id,
        trace_id=unified_message.trace_id,
        in_reply_to=unified_message.message_id,
    )

    # ── 6. Envoi via sender canal ─────────────────────────────────────────────
    sender = get_sender(unified_message.channel)
    if not sender:
        logger.error("omnicall_v9.bloc10.no_sender channel=%s", unified_message.channel)
        v9_circuit.record_error()
        return DispatchResult(
            dispatched_by_v9=False,
            send_result=None,
            pipeline_result=pipeline,
            v8_fallback_reason=f"no_sender:{unified_message.channel}",
        )

    # Injecter le store pour BYOK
    if hasattr(sender, '_store'):
        sender._store = store

    send_result = await sender.send(agent_reply)

    # ── 7. Circuit breaker + métriques ───────────────────────────────────────
    if send_result.success:
        v9_circuit.record_success()
    else:
        v9_circuit.record_error()

    latency_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "omnicall_v9.bloc10.dispatched",
        extra={
            "channel": str(unified_message.channel),
            "store_id": store_id,
            "route": str(pipeline.route),
            "fsm_state": str(pipeline.fsm_state),
            "send_success": send_result.success,
            "latency_ms": round(latency_ms, 1),
            "provider_msg_id": send_result.provider_message_id,
        },
    )

    return DispatchResult(
        dispatched_by_v9=True,
        send_result=send_result,
        pipeline_result=pipeline,
        latency_ms=round(latency_ms, 1),
    )
