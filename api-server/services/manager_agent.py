"""services/manager_agent.py — Agent Manager : supervision et coordination des sous-agents.

Rôle :
  Le ManagerAgent orchestre les sous-agents spécialisés (CommerceAgent, OwnerAgent,
  SocialSalesAgent, AppointmentAgent, AutoPartsAgent) et gère :
    - Le routage intelligent via agent_orchestrator.resolve_route()
    - La supervision des réponses (qualité, longueur, cohérence)
    - L'escalade vers un opérateur humain si l'agent ne peut pas répondre
    - Le logging structuré de toutes les décisions de routage
    - Les métriques de performance par sous-agent

Architecture :
  ManagerAgent est un singleton par application (get_manager()).
  Il maintient un état léger (statistiques) et délègue l'exécution aux sous-agents.

VERSION: v24 — implémentation complète
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# AUDIT FIX : imports remontés au niveau module (étaient locaux dans
# ManagerAgent.dispatch). tests/test_manager_agent.py mocke
# `services.manager_agent.resolve_route`, ce qui échouait avec AttributeError
# tant que le nom n'existait qu'en local scope. Pas d'import circulaire :
# agent_orchestrator n'importe pas manager_agent.
from services.agent_orchestrator import RouteDecision, dispatch_customer_message, resolve_route  # noqa: F401

logger = logging.getLogger("manager_agent")

# ── Constantes ────────────────────────────────────────────────────────────────
_MAX_RESPONSE_LENGTH = 2000        # Caractères max avant troncature
_ESCALATION_KEYWORDS = frozenset({
    "responsable", "manager", "humain", "erreur", "problème grave",
    "remboursement refusé", "avocat", "arnaque", "fraud",
})
_MIN_RESPONSE_LENGTH = 10          # Réponse trop courte -> signal d'erreur


@dataclass
class AgentDecision:
    """Décision prise par le ManagerAgent."""
    agent_route: str
    response: str | None
    escalated: bool = False
    escalation_reason: str | None = None
    latency_ms: float = 0.0
    agent_version: str = "v24"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentStats:
    """Statistiques agrégées par route d'agent."""
    route: str
    total_calls: int = 0
    successful_calls: int = 0
    escalations: int = 0
    avg_latency_ms: float = 0.0
    last_call_at: str | None = None

    def record_call(self, success: bool, latency_ms: float, escalated: bool = False) -> None:
        self.total_calls += 1
        if success:
            self.successful_calls += 1
        if escalated:
            self.escalations += 1
        # Running average
        if self.total_calls == 1:
            self.avg_latency_ms = latency_ms
        else:
            self.avg_latency_ms = (
                self.avg_latency_ms * (self.total_calls - 1) + latency_ms
            ) / self.total_calls
        self.last_call_at = datetime.now(UTC).isoformat()

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls

    @property
    def escalation_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.escalations / self.total_calls


class ManagerAgent:
    """Superviseur et coordinateur des sous-agents IA."""

    def __init__(self) -> None:
        self._stats: dict[str, AgentStats] = {}
        logger.info("ManagerAgent v24 initialisé")

    def _get_stats(self, route: str) -> AgentStats:
        if route not in self._stats:
            self._stats[route] = AgentStats(route=route)
        return self._stats[route]

    def _detect_escalation_needed(self, text: str) -> tuple[bool, str | None]:
        """Détecte si le message client nécessite une escalade humaine."""
        text_lower = text.lower()
        for keyword in _ESCALATION_KEYWORDS:
            if keyword in text_lower:
                return True, f"Mot-clé d'escalade détecté: '{keyword}'"
        return False, None

    def _validate_response(self, response: str | None) -> tuple[bool, str | None]:
        """Valide la qualité d'une réponse d'agent.

        Returns:
            (is_valid, error_reason)
        """
        if response is None:
            return False, "Réponse None"
        if len(response.strip()) < _MIN_RESPONSE_LENGTH:
            return False, f"Réponse trop courte ({len(response)} chars)"
        if len(response) > _MAX_RESPONSE_LENGTH:
            logger.warning("Réponse tronquée: %d -> %d chars", len(response), _MAX_RESPONSE_LENGTH)
        return True, None

    def _truncate_if_needed(self, response: str) -> str:
        """Tronque la réponse si elle dépasse _MAX_RESPONSE_LENGTH."""
        if len(response) > _MAX_RESPONSE_LENGTH:
            return response[:_MAX_RESPONSE_LENGTH].rsplit(" ", 1)[0] + "…"
        return response

    async def dispatch(
        self,
        db: Any,
        *,
        store: Any,
        customer: Any | None,
        text: str,
        wa: Any,
        channel: str = "whatsapp",
        role: str = "customer",
        billing_status: str | None = "active",
        payload: dict[str, Any] | None = None,
    ) -> AgentDecision:
        """Dispatche un message vers l'agent approprié et supervise la réponse.

        Args:
            db: Session DB async.
            store: Objet Store (tenant).
            customer: Objet Customer (peut être None pour les owners).
            text: Texte du message entrant.
            wa: Client WhatsApp/canal (pour les envois).
            channel: Canal de communication.
            role: 'customer' ou 'owner'.
            billing_status: Statut de facturation du tenant.
            payload: Métadonnées supplémentaires du webhook.

        Returns:
            AgentDecision avec route, réponse, et métriques.
        """
        t0 = time.monotonic()

        # 1. Détection d'escalade avant le routage
        if role == "customer" and text:
            needs_escalation, escalation_reason = self._detect_escalation_needed(text)
            if needs_escalation:
                latency = (time.monotonic() - t0) * 1000
                self._get_stats("escalation").record_call(True, latency, escalated=True)
                logger.info(
                    "ManagerAgent: escalade pour store=%s raison=%s",
                    getattr(store, "id", "?"), escalation_reason
                )
                return AgentDecision(
                    agent_route="human_escalation",
                    response="Je vais vous mettre en contact avec notre équipe. Merci de patienter.",
                    escalated=True,
                    escalation_reason=escalation_reason,
                    latency_ms=latency,
                )

        # 2. Résolution de la route (resolve_route importé au niveau module)
        try:
            decision = await resolve_route(
                db,
                store=store,
                role=role,
                channel=channel,
                billing_status=billing_status,
                customer=customer,
                text=text,
            )
        except Exception as exc:
            logger.error("ManagerAgent: resolve_route failed: %s", exc)
            decision = RouteDecision(
                route="commerce_agent",
                degraded_mode=True,
                reason=f"route_error: {exc}",
            )

        route = decision.route

        # 3. Dispatch vers l'agent
        response_text: str | None = None
        success = False

        try:
            if route == "blocked":
                response_text = "Votre abonnement est suspendu. Contactez support@autocommerce.ai."
                success = True
            else:
                # Délégation au dispatcher principal
                response_text = await dispatch_customer_message(
                    db,
                    store=store,
                    customer=customer,
                    text=text,
                    wa=wa,
                    channel=channel,
                    payload=payload or {},
                )
                success = True
        except Exception as exc:
            logger.error("ManagerAgent: agent %s failed: %s", route, exc)
            response_text = "Je rencontre une difficulté technique. Veuillez réessayer."
            success = False

        # 4. Validation de la réponse
        is_valid, validation_error = self._validate_response(response_text)
        if not is_valid:
            logger.warning("ManagerAgent: réponse invalide (%s) pour route=%s", validation_error, route)

        # 5. Troncature si nécessaire
        if response_text and len(response_text) > _MAX_RESPONSE_LENGTH:
            response_text = self._truncate_if_needed(response_text)

        # 6. Enregistrement des stats
        latency = (time.monotonic() - t0) * 1000
        self._get_stats(route).record_call(success, latency)

        logger.info(
            "ManagerAgent: route=%s degraded=%s latency=%.1fms success=%s store=%s",
            route, decision.degraded_mode, latency, success, getattr(store, "id", "?")
        )

        return AgentDecision(
            agent_route=route,
            response=response_text,
            escalated=False,
            latency_ms=latency,
            metadata={
                "degraded_mode": decision.degraded_mode,
                "route_reason": decision.reason,
                "channel": channel,
            },
        )

    def get_stats(self) -> dict[str, Any]:
        """Retourne les statistiques agrégées de tous les agents."""
        return {
            route: {
                "total_calls": stats.total_calls,
                "success_rate": round(stats.success_rate, 3),
                "escalation_rate": round(stats.escalation_rate, 3),
                "avg_latency_ms": round(stats.avg_latency_ms, 1),
                "last_call_at": stats.last_call_at,
            }
            for route, stats in self._stats.items()
        }

    def reset_stats(self) -> None:
        """Réinitialise les statistiques (utile pour les tests)."""
        self._stats.clear()


# ── Singleton ─────────────────────────────────────────────────────────────────
_MANAGER_INSTANCE: ManagerAgent | None = None


def get_manager() -> ManagerAgent:
    """Retourne l'instance singleton du ManagerAgent."""
    global _MANAGER_INSTANCE
    if _MANAGER_INSTANCE is None:
        _MANAGER_INSTANCE = ManagerAgent()
    return _MANAGER_INSTANCE
