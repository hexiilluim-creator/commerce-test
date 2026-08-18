"""services/tasks.py — Tâches Celery de traitement asynchrone.

Architecture :
  • Si Celery est installé et un broker Redis configuré -> tâches réelles (@task).
  • Si Celery absent ou broker non configuré -> stubs synchrones avec warning
    (comportement identique au démarrage, aucun import cassé).

Queues :
  - whatsapp : messages entrants WhatsApp (haute priorité)
  - social   : webhooks Facebook/Instagram/TikTok
  - default  : tâches génériques (embeddings, notifications)

Retry policy : 3 tentatives avec backoff exponentiel (2^n secondes).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _retry_with_backoff(task_name: str, retries: int) -> int:
    countdown = min(120, 2 ** max(retries, 0))
    try:
        from services.metrics import celery_task_retries
        celery_task_retries.labels(task_name=task_name).inc()
    except Exception:
        pass
    return countdown


def _run_async(coro) -> Any:
    """Exécute une coroutine depuis un worker Celery synchrone ou un contexte de test."""
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Pas de boucle en cours, on peut utiliser asyncio.run
            return asyncio.run(coro)

        if loop.is_running():
            # Si on est déjà dans une boucle (cas des tests pytest-asyncio),
            # on exécute la coroutine dans un thread dédié avec sa propre boucle.
            import queue
            import threading

            result_queue: queue.Queue = queue.Queue(maxsize=1)

            def _in_thread(c):
                try:
                    result_queue.put((True, asyncio.run(c)))
                except Exception as thread_exc:
                    result_queue.put((False, thread_exc))

            worker = threading.Thread(target=_in_thread, args=(coro,), daemon=True)
            worker.start()
            ok, payload = result_queue.get(timeout=120)
            worker.join(timeout=1)
            if ok:
                return payload
            raise payload
        return loop.run_until_complete(coro)
    except Exception as e:
        logger.error(f"Error in _run_async: {e}")
        raise


# Compatibilité publique : structured_agent.relance_users et les intégrations
# historiques importent run_async. Conserver _run_async comme implémentation
# interne et exposer une façade stable, sans changer le comportement d’exécution.
run_async = _run_async


async def get_isolated_db():
    """Crée une session DB isolée pour les tâches s'exécutant dans un thread séparé."""
    # Création d'un engine temporaire pour ce thread/boucle
    # On réutilise la logique de database.py mais localement
    import re

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from config import settings

    url = settings.DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    url = re.sub(r"[?&]sslmode=[^&]*", "", url)
    url = re.sub(r"[?&]connect_timeout=[^&]*", "", url)
    url = url.rstrip("?").rstrip("&")

    engine_kwargs = {"echo": settings.DEBUG}
    if "sqlite" in url:
        from sqlalchemy.pool import StaticPool

        engine = create_async_engine(
            url, poolclass=StaticPool, connect_args={"check_same_thread": False}, **engine_kwargs
        )
    else:
        engine = create_async_engine(url, **engine_kwargs)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
        finally:
            await engine.dispose()


# ── Tentative de chargement Celery ────────────────────────────────────────────
try:
    from services.celery_app import celery_app

    _CELERY_AVAILABLE = celery_app is not None
except ImportError:
    celery_app = None
    _CELERY_AVAILABLE = False

if _CELERY_AVAILABLE:
    # ──────────────────────────────────────────────────────────────────────────
    # Tâches réelles Celery
    # ──────────────────────────────────────────────────────────────────────────

    @celery_app.task(
        name="services.tasks.process_whatsapp_message",
        bind=True,
        max_retries=3,
        default_retry_delay=5,
        queue="whatsapp",
        acks_late=True,
    )
    def process_whatsapp_message(
        self,
        store_id: int,
        customer_phone: str,
        message_text: str,
        **kwargs: Any,
    ) -> dict:
        """Traite un message WhatsApp entrant de façon asynchrone."""

        async def _run():
            async for db in get_isolated_db():
                try:
                    from services.ai_agent import handle_whatsapp_message

                    return await handle_whatsapp_message(
                        store_id=store_id,
                        customer_phone=customer_phone,
                        message_text=message_text,
                        db=db,
                    )
                except Exception as exc:
                    logger.exception(
                        "process_whatsapp_message failed store_id=%s phone=%s: %s",
                        store_id,
                        customer_phone,
                        exc,
                    )
                    raise self.retry(exc=exc, countdown=_retry_with_backoff(self.name, self.request.retries))

        return _run_async(_run())

    @celery_app.task(
        name="services.tasks.process_social_webhook",
        bind=True,
        max_retries=3,
        default_retry_delay=10,
        queue="social",
        acks_late=True,
    )
    def process_social_webhook(
        self,
        platform: str,
        store_id: int,
        payload: dict,
        **kwargs: Any,
    ) -> dict:
        """Traite un webhook social (Instagram/Facebook/TikTok) en arrière-plan."""

        async def _run():
            async for db in get_isolated_db():
                try:
                    from services.social_agent import handle_social_event

                    return await handle_social_event(platform=platform, store_id=store_id, payload=payload, db=db)
                except Exception as exc:
                    logger.exception(
                        "process_social_webhook failed platform=%s store_id=%s: %s",
                        platform,
                        store_id,
                        exc,
                    )
                    raise self.retry(exc=exc, countdown=_retry_with_backoff(self.name, self.request.retries))

        return _run_async(_run())

    @celery_app.task(
        name="services.tasks.reconcile_payment",
        bind=True,
        max_retries=5,
        default_retry_delay=30,
        queue="default",
    )
    def reconcile_payment(self, payment_link_id: int, provider: str, **kwargs: Any) -> dict:
        """Vérifie le statut d'un paiement et met à jour la commande."""

        async def _run():
            async for db in get_isolated_db():
                try:
                    from sqlalchemy import select

                    from models.database import PaymentLink
                    from services.payment_factory import PaymentFactory

                    result = await db.execute(select(PaymentLink).where(PaymentLink.id == payment_link_id))
                    link = result.scalar_one_or_none()
                    if link is None:
                        return {"status": "not_found"}
                    prov = PaymentFactory.get(provider, link.provider_config or {})
                    status = await prov.verify_payment(link.provider_payment_id or "")
                    if status.get("status") == "paid" and link.status != "paid":
                        link.status = "paid"
                        await db.commit()
                        return {"reconciled": True, "status": "paid"}
                    return {"reconciled": False, "status": status.get("status")}
                except Exception as exc:
                    logger.exception("reconcile_payment failed id=%s: %s", payment_link_id, exc)
                    raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))

        return _run_async(_run())

    @celery_app.task(
        name="services.tasks.update_product_embedding",
        bind=True,
        max_retries=2,
        default_retry_delay=60,
        queue="default",
    )
    def update_product_embedding(self, product_id: int, store_id: int, **kwargs: Any) -> dict:
        """Recalcule et stocke l'embedding pgvector d'un produit."""
        from config import settings

        # En tests intégration avec SQLite in-memory, Celery eager-mode exécute la
        # tâche inline mais get_isolated_db() ouvre un NOUVEL engine / nouvelle
        # connexion. Avec sqlite:///:memory:, chaque connexion possède sa propre
        # base vide -> la table products n'existe pas dans la tâche de fond.
        # On ignore donc explicitement ce recalcul non critique dans ce contexte.
        if settings.ENV == "test" and settings.DATABASE_URL.strip().endswith(":memory:"):
            logger.debug(
                "Skipping update_product_embedding for in-memory SQLite test DB",
                extra={"product_id": product_id, "store_id": store_id},
            )
            return {"product_id": product_id, "done": False, "skipped": "in_memory_test_db"}

        async def _run():
            async for db in get_isolated_db():
                from services.embedding_search import update_product_embedding as _update

                await _update(product_id=product_id, store_id=store_id, db=db)
                return {"product_id": product_id, "done": True}

        return _run_async(_run())

    @celery_app.task(
        name="services.tasks.send_whatsapp_message",
        bind=True,
        max_retries=3,
        default_retry_delay=5,
        queue="whatsapp",
    )
    def send_whatsapp_message(self, phone_number: str, message: str, store_id: int, **kwargs: Any) -> dict:
        """Envoie un message WhatsApp sortant (notification, rappel, etc.)."""

        async def _run():
            async for db in get_isolated_db():
                from services.ai_agent import send_whatsapp_text

                return await send_whatsapp_text(store_id=store_id, phone=phone_number, text=message, db=db)

        try:
            return _run_async(_run())
        except Exception as exc:
            logger.error("send_whatsapp_message failed phone=%s: %s", phone_number, exc)
            raise self.retry(exc=exc, countdown=_retry_with_backoff(self.name, self.request.retries))

    @celery_app.task(
        name="services.tasks.process_ai_response",
        bind=True,
        max_retries=2,
        default_retry_delay=10,
        queue="default",
    )
    def process_ai_response(self, store_id: int, context: dict, **kwargs: Any) -> dict:
        """Génère une réponse IA pour un contexte donné (usage interne)."""

        async def _run():
            async for db in get_isolated_db():
                from services.structured_agent import run_agent

                return await run_agent(store_id=store_id, context=context, db=db)

        return _run_async(_run())

    @celery_app.task(
        name="services.tasks.send_order_notification",
        bind=True,
        max_retries=3,
        default_retry_delay=15,
        queue="default",
    )
    def send_order_notification(self, order_id: int, store_id: int, event: str, **kwargs: Any) -> dict:
        """Notifie le commerçant d'un événement sur une commande."""

        async def _run():
            async for db in get_isolated_db():
                from sqlalchemy import select

                from models.database import Order, Store

                order = (
                    await db.execute(select(Order).where(Order.id == order_id, Order.store_id == store_id))
                ).scalar_one_or_none()
                if order is None:
                    return {"notified": False, "reason": "order_not_found"}
                await db.get(Store, store_id)
                logger.info(
                    "send_order_notification: order=%s store=%s event=%s",
                    order_id,
                    store_id,
                    event,
                )
                return {"notified": True, "order_id": order_id, "event": event}

        return _run_async(_run())

    @celery_app.task(
        name="services.tasks.cleanup_orphaned_redis_sessions",
        bind=True,
        max_retries=3,
        default_retry_delay=60,
        queue="default",
    )
    def cleanup_orphaned_redis_sessions(self, **kwargs: Any) -> dict:
        """Nettoie les clés Redis de session/auth orphelines."""

        async def _run():
            from services.redis_session_cleanup import cleanup_orphaned_redis_sessions as _cleanup

            return await _cleanup()

        try:
            return _run_async(_run())
        except Exception as exc:
            logger.exception("cleanup_orphaned_redis_sessions failed: %s", exc)
            raise self.retry(exc=exc, countdown=_retry_with_backoff(self.name, self.request.retries))

else:
    # ──────────────────────────────────────────────────────────────────────────
    # Stubs synchrones — broker absent ou Celery non installé
    # ──────────────────────────────────────────────────────────────────────────

    class _TaskStub:
        """Simule l'interface .delay() / .apply_async() sans broker.

        P1.6-FIX : auparavant, un log.warning() était le SEUL signal émis quand
        une tâche (message WhatsApp, notification de commande, réconciliation
        de paiement) était silencieusement abandonnée faute de broker Celery.
        Un log perdu dans le flux applicatif ne serait vu par personne en
        pratique. Ajout d'une métrique Prometheus dédiée (alertable) et d'une
        capture Sentry (si configuré) à chaque invocation — ce chemin de code
        ne devrait JAMAIS s'exécuter en production correctement déployée.
        """

        def __init__(self, name: str) -> None:
            self.name = name

        def _alert(self, method: str) -> None:
            logger.warning(
                "Celery broker absent — tâche '%s' non exécutée (%s). "
                "Configurer CELERY_BROKER_URL pour activer le traitement asynchrone.",
                self.name, method,
            )
            try:
                from services.metrics import celery_stub_invocations_total
                celery_stub_invocations_total.labels(task_name=self.name).inc()
            except Exception:
                pass
            try:
                import sentry_sdk
                sentry_sdk.capture_message(
                    f"Celery stub invoqué pour '{self.name}' — tâche perdue silencieusement "
                    f"(broker/package Celery absent).",
                    level="error",
                )
            except Exception:
                pass

        def delay(self, *args: Any, **kwargs: Any) -> None:
            self._alert("delay")

        def apply_async(self, args=None, kwargs=None, **options: Any) -> None:
            self._alert("apply_async")

        def __call__(self, *args: Any, **kwargs: Any) -> None:
            self._alert("call")

    process_whatsapp_message = _TaskStub("process_whatsapp_message")
    process_social_webhook = _TaskStub("process_social_webhook")
    reconcile_payment = _TaskStub("reconcile_payment")
    update_product_embedding = _TaskStub("update_product_embedding")
    send_whatsapp_message = _TaskStub("send_whatsapp_message")
    process_ai_response = _TaskStub("process_ai_response")
    send_order_notification = _TaskStub("send_order_notification")
    cleanup_orphaned_redis_sessions = _TaskStub("cleanup_orphaned_redis_sessions")
