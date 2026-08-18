"""Shared pytest bootstrap for AutoCommerce V25 merged delivery.

Ensures required environment variables are present before importing app modules.

BLOC 4 — Extension :
    * Mocks complets pour services tiers (WhatsApp, Stripe, OpenAI) via des
      fixtures auto-utilisables, afin que la suite de tests puisse s'exécuter
      sans clés API réelles.
    * Fixture ``mock_third_party_services`` en ``autouse=True`` sur ``session``
      pour patcher httpx / openai / stripe globalement.

P1.7-FIX (audit déploiement, juillet 2026) : tous les ``os.environ.setdefault()``
ci-dessous ne s'appliquent QUE si la variable n'est pas déjà présente dans
l'environnement shell. Si un ``.env`` contenant de vraies valeurs (ex:
``FEATURE_FLAG_DEEPSEEK=false``, ``INTERNAL_HEALTH_TOKEN=<vraie clé>``) a été
sourcé AVANT de lancer pytest (``source .env && pytest ...``), ces valeurs
gagnent silencieusement sur les défauts de test ci-dessous — provoquant des
échecs de tests qui ressemblent à des bugs de code mais n'en sont pas
(diagnostiqué en conditions réelles : ``test_chat_deepseek_primary_success``
et ``test_credits_monthly_stats_with_months_param`` échouaient uniquement
pour cette raison). Lancer la suite dans un shell propre, sans ``.env``
sourcé au préalable.
"""
from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if API_ROOT not in sys.path:
    sys.path.insert(0, API_ROOT)

# Core app
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-chars-minimum-ok!")
os.environ.setdefault("CORS_ORIGINS", "http://testserver")
os.environ.setdefault("SKIP_LIMITER", "1")

# Integrations / webhooks
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-app-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-verify-token")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test-whatsapp-access-token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "1234567890")
os.environ.setdefault("INSTAGRAM_APP_SECRET", "")
os.environ.setdefault("FACEBOOK_APP_SECRET", "")
os.environ.setdefault("TIKTOK_APP_SECRET", "")
os.environ.setdefault("INSTAGRAM_VERIFY_TOKEN", "test-ig-token")
os.environ.setdefault("FACEBOOK_VERIFY_TOKEN", "test-fb-token")
os.environ.setdefault("TIKTOK_VERIFY_TOKEN", "test-tt-token")
os.environ.setdefault("TIKTOK_ENABLED", "false")

# Stripe
os.environ.setdefault("STRIPE_API_KEY", "sk_test_00000000000000000000000000000000")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_00000000000000000000000000000000")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_0000000000000000000000000000000000000000")
os.environ.setdefault("STRIPE_PUBLISHABLE_KEY", "pk_test_0000000000000000000000000000")

# AI / LLM
os.environ.setdefault("OPENAI_API_KEY", "sk-test-000000000000000000000000000000000000000000000000")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-0000")
os.environ.setdefault("DEEPSEEK_API_KEY", "ds-test-000000000000000000000000")
os.environ.setdefault("FEATURE_FLAG_DEEPSEEK", "true")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token-001")
os.environ.setdefault("LLM_PROVIDER", "stub")
os.environ.setdefault("VISION_PROVIDER", "stub")
os.environ.setdefault("LOYALTY_IA_ENABLED", "true")
os.environ.setdefault("PREDICTIVE_RESTOCKING_ENABLED", "true")

# Misc
os.environ.setdefault("SUPER_ADMIN_SECRET", "super-secret-test")
os.environ.setdefault("SENDGRID_API_KEY", "SG.test.test")
os.environ.setdefault("FROM_EMAIL", "test@example.com")
os.environ.setdefault("FLOUCI_APP_TOKEN", "test-flouci-token")
os.environ.setdefault("FLOUCI_APP_SECRET", "test-flouci-secret")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
os.environ.setdefault("AWS_REGION", "eu-west-1")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token-001")
os.environ.setdefault("SERVER_DOMAIN", "https://test.example.com")


# ═══════════════════════════════════════════════════════════════════════════════
# BLOC 4 — Mocks complets pour services tiers
# ═══════════════════════════════════════════════════════════════════════════════
#
# Objectif : la suite de tests ne doit jamais dépendre d'une clé API réelle
# ni provoquer un appel réseau vers WhatsApp, Stripe, OpenAI, Anthropic ou
# SendGrid. Les fixtures ci-dessous fournissent des mocks canoniques et
# activent automatiquement le patching global.
#
# Utilisation ciblée dans un test :
#     def test_send_message(mock_whatsapp_client):
#         mock_whatsapp_client.send_message.return_value = {"messages":[{"id":"wamid.XYZ"}]}
#         ...
#
# Utilisation automatique :
#     La fixture ``mock_third_party_services`` est autouse=True et patche
#     httpx.AsyncClient, openai et stripe pour toute la session de tests.
# ═══════════════════════════════════════════════════════════════════════════════


# ─── WhatsApp Cloud API mock ─────────────────────────────────────────────────

class _WhatsAppMockClient:
    """Mock du client WhatsApp Business Cloud API.

    Simule l'envoi de messages, l'upload de médias et la vérification de
    signatures webhook — sans jamais contacter Facebook Graph API.
    """

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []
        self.uploaded_media: list[dict[str, Any]] = []
        self.send_message = AsyncMock(side_effect=self._send_message)
        self.send_template = AsyncMock(side_effect=self._send_template)
        self.upload_media = AsyncMock(side_effect=self._upload_media)
        self.mark_as_read = AsyncMock(return_value={"success": True})
        self.get_media_url = AsyncMock(return_value="https://mock-cdn.whatsapp.test/media/abc")

    async def _send_message(self, to: str, body: str, **kwargs: Any) -> dict[str, Any]:
        message_id = f"wamid.TEST_{len(self.sent_messages) + 1:06d}"
        payload = {"to": to, "body": body, "message_id": message_id, **kwargs}
        self.sent_messages.append(payload)
        return {"messaging_product": "whatsapp", "messages": [{"id": message_id}]}

    async def _send_template(self, to: str, template_name: str, **kwargs: Any) -> dict[str, Any]:
        return await self._send_message(to, f"[template:{template_name}]", **kwargs)

    async def _upload_media(self, file_bytes: bytes, mime_type: str) -> dict[str, Any]:
        media_id = f"MEDIA_TEST_{len(self.uploaded_media) + 1:06d}"
        self.uploaded_media.append({"media_id": media_id, "mime": mime_type, "size": len(file_bytes)})
        return {"id": media_id}


@pytest.fixture
def mock_whatsapp_client() -> _WhatsAppMockClient:
    """Fournit un client WhatsApp mocké prêt à l'emploi pour un test."""
    return _WhatsAppMockClient()


# ─── Stripe mock ─────────────────────────────────────────────────────────────

class _StripeMockAPI:
    """Mock de l'API Stripe (checkout, webhooks, customers).

    N'importe jamais le SDK réel : renvoie des payloads compatibles avec la
    forme des objets Stripe (``id``, ``object``, ``status``…).
    """

    def __init__(self) -> None:
        self.created_sessions: list[dict[str, Any]] = []
        self.webhook_events: list[dict[str, Any]] = []

    def create_checkout_session(self, **kwargs: Any) -> dict[str, Any]:
        session_id = f"cs_test_{len(self.created_sessions) + 1:06d}"
        session = {
            "id": session_id,
            "object": "checkout.session",
            "url": f"https://checkout.stripe.test/pay/{session_id}",
            "status": "open",
            "payment_status": "unpaid",
            "amount_total": kwargs.get("amount_total", 2999),
            "currency": kwargs.get("currency", "usd"),
            "customer": kwargs.get("customer", "cus_test_XXX"),
            "metadata": kwargs.get("metadata", {}),
        }
        self.created_sessions.append(session)
        return session

    def construct_webhook_event(
        self, payload: bytes | str, signature: str, secret: str
    ) -> dict[str, Any]:
        """Simule stripe.Webhook.construct_event.

        Ne vérifie pas cryptographiquement la signature : accepte toute
        signature non vide, rejette une signature vide (comportement utile
        pour distinguer 'valide' vs 'invalide' dans les tests).
        """
        if not signature:
            raise ValueError("No signatures found matching the expected signature for payload")
        event = {
            "id": f"evt_test_{len(self.webhook_events) + 1:06d}",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_000001", "payment_status": "paid"}},
            "livemode": False,
        }
        self.webhook_events.append(event)
        return event


@pytest.fixture
def mock_stripe_api() -> _StripeMockAPI:
    """Fournit une API Stripe mockée prête à l'emploi."""
    return _StripeMockAPI()


# ─── OpenAI mock ─────────────────────────────────────────────────────────────

class _OpenAIMockClient:
    """Mock du client OpenAI (chat completions, embeddings, moderations)."""

    def __init__(self) -> None:
        self.chat_calls: list[dict[str, Any]] = []
        self.embedding_calls: list[dict[str, Any]] = []
        self.default_reply = "Ceci est une réponse simulée par le mock OpenAI."

    async def chat_completion(
        self, model: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        self.chat_calls.append({"model": model, "messages": messages, **kwargs})
        return {
            "id": f"chatcmpl-test-{len(self.chat_calls):06d}",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": self.default_reply},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        }

    async def embedding(self, model: str, input_text: str | list[str]) -> dict[str, Any]:
        self.embedding_calls.append({"model": model, "input": input_text})
        n = 1 if isinstance(input_text, str) else len(input_text)
        return {
            "object": "list",
            "model": model,
            "data": [
                {"object": "embedding", "index": i, "embedding": [0.001] * 1536}
                for i in range(n)
            ],
            "usage": {"prompt_tokens": 4 * n, "total_tokens": 4 * n},
        }

    async def moderate(self, input_text: str) -> dict[str, Any]:
        return {
            "id": "modr-test",
            "model": "text-moderation-latest",
            "results": [{"flagged": False, "categories": {}, "category_scores": {}}],
        }


@pytest.fixture
def mock_openai_client() -> _OpenAIMockClient:
    """Fournit un client OpenAI mocké prêt à l'emploi."""
    return _OpenAIMockClient()


# ─── httpx global patch (bloque tout appel réseau sortant) ───────────────────

class _MockHTTPResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text or (str(self._json) if self._json else "")
        self.headers = {"content-type": "application/json"}
        self.content = self.text.encode("utf-8")

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"Mock HTTP error {self.status_code}")


def _default_httpx_response(*args: Any, **kwargs: Any) -> _MockHTTPResponse:
    """Réponse HTTP par défaut renvoyée par le mock httpx global.

    Route sur l'URL pour renvoyer un payload plausible :
      - graph.facebook.com  -> réponse WhatsApp
      - api.stripe.com      -> réponse Stripe checkout
      - api.openai.com      -> réponse chat completion
      - autres              -> {"ok": true}
    """
    url = ""
    if args:
        url = str(args[0]) if args else ""
    elif "url" in kwargs:
        url = str(kwargs["url"])

    if "graph.facebook.com" in url or "whatsapp" in url.lower():
        return _MockHTTPResponse(
            200, {"messaging_product": "whatsapp", "messages": [{"id": "wamid.MOCK"}]}
        )
    if "api.stripe.com" in url:
        return _MockHTTPResponse(
            200,
            {
                "id": "cs_test_mock",
                "object": "checkout.session",
                "url": "https://checkout.stripe.test/pay/cs_test_mock",
                "status": "open",
                "payment_status": "unpaid",
            },
        )
    if "api.openai.com" in url or "api.anthropic.com" in url or "api.deepseek.com" in url:
        return _MockHTTPResponse(
            200,
            {
                "id": "chatcmpl-mock",
                "choices": [
                    {"message": {"role": "assistant", "content": "mock reply"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )
    if "sendgrid" in url.lower():
        return _MockHTTPResponse(202, {"message": "queued"})
    return _MockHTTPResponse(200, {"ok": True})


def _is_asgi_test_transport(transport: Any) -> bool:
    """True si le transport appartient à Starlette/httpx TestClient (ASGI in-process),
    False si c'est un transport HTTP réel (réseau sortant réel à bloquer).

    P1-FIX (V28-FIXED-P1) : l'ancienne implémentation remplaçait purement et
    simplement `httpx.Client`/`httpx.AsyncClient` par un MagicMock. Or Starlette's
    `TestClient` HÉRITE de `httpx.Client` (`class TestClient(httpx.Client)`) — en
    remplaçant la classe elle-même, `TestClient(app)` ne construisait plus un vrai
    client mais renvoyait directement le mock, cassant TOUTE route testée via
    `TestClient`/FastAPI `TestClient` (aucun appel réseau réel n'est pourtant en jeu :
    le transport ASGI de test tourne entièrement en mémoire, sans I/O réseau).
    """
    if transport is None:
        return False
    mod = type(transport).__module__ or ""
    name = type(transport).__name__ or ""
    return mod.startswith("starlette") or name in ("ASGITransport",)


@pytest.fixture(scope="session", autouse=True)
def mock_third_party_services():
    """Bloque tout appel HTTP sortant RÉEL pour toute la session de tests
    (WhatsApp, Stripe, OpenAI, Anthropic, SendGrid, etc.), sans casser
    `TestClient` (FastAPI/Starlette) qui utilise httpx en interne pour router
    les requêtes de test en mémoire (aucun réseau impliqué).

    P1-FIX : on ne remplace plus les classes `httpx.Client`/`httpx.AsyncClient`
    (Starlette's `TestClient` en hérite directement) ; on patche uniquement
    leur méthode `send()`. Si le client utilise le transport ASGI de test
    (`TestClient`), la requête passe par l'implémentation réelle — 100% en
    mémoire, aucune fuite réseau possible. Sinon (transport HTTP réel = un
    provider tiers), on renvoie une réponse mockée déterministe.

    Les tests qui veulent vérifier des payloads précis peuvent surcharger
    localement, ou utiliser les fixtures ciblées `mock_whatsapp_client` /
    `mock_stripe_api` / `mock_openai_client`.
    """
    real_sync_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def _fake_sync_send(self: httpx.Client, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if _is_asgi_test_transport(getattr(self, "_transport", None)):
            return real_sync_send(self, request, **kwargs)
        fake = _default_httpx_response(str(request.url))
        return httpx.Response(fake.status_code, json=fake.json(), request=request)

    async def _fake_async_send(self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if _is_asgi_test_transport(getattr(self, "_transport", None)):
            return await real_async_send(self, request, **kwargs)
        fake = _default_httpx_response(str(request.url))
        return httpx.Response(fake.status_code, json=fake.json(), request=request)

    patches: list[Any] = []
    try:
        patches.append(patch.object(httpx.Client, "send", _fake_sync_send))
        patches.append(patch.object(httpx.AsyncClient, "send", _fake_async_send))
    except Exception:
        # httpx pas installé : on ignore silencieusement.
        pass

    started = []
    for p in patches:
        try:
            started.append(p.start())
        except Exception:
            pass

    yield

    for p in patches:
        try:
            p.stop()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# PASSE 2 — Mocks globaux Redis et Celery (élimine les échecs CI Redis/Celery)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Problème identifié lors de l'audit de la 2e passe :
#   • conftest.py définissait REDIS_URL mais ne substituait JAMAIS le vrai
#     client Redis. 30+ fichiers de test patchaient `redis_lock.get_redis`
#     localement — code dupliqué, fragile, incomplet.
#   • Celery est installé. Quand un route handler appelle .delay() (ex:
#     process_whatsapp_message), Celery contacte redis://localhost:6379/0.
#     En CI (pas de Redis), ConnectionRefusedError → test échoue.
#   • lib.redis_client._pool s'initialisait à l'import → crash TCP aléatoire.
#
# Corrections :
#   1. _AsyncMemRedis  : client Redis in-memory async complet.
#   2. _AsyncMemPipeline : pipeline in-memory.
#   3. mock_redis_globally : fixture session autouse — patch les 4 points
#      d'entrée Redis du projet.
#   4. mock_celery_globally : fixture session autouse — force
#      task_always_eager=True (tâches synchrones, sans broker).
#
# Compatibilité garantie :
#   Les tests qui font déjà `with patch("services.redis_lock.get_redis", ...)`
#   en local continuent de fonctionner — leur patch surcharge temporairement
#   le mock session et est restauré à la sortie du contexte `with`.
# ═══════════════════════════════════════════════════════════════════════════════

import time as _time_module


class _AsyncMemRedis:
    """Client Redis async in-memory — couvre tous les ops utilisés par le projet.

    Implémente : GET/SET/SETEX/EXISTS/DELETE/EXPIRE/INCR/INCRBY/DECRBY,
    PUBLISH, LPUSH/RPUSH/LTRIM/LRANGE, XADD/XLEN/XGROUP_CREATE/XREADGROUP/
    XACK/XAUTOCLAIM/XPENDING, PING, pipeline().
    """

    def __init__(self) -> None:
        self._kv: dict[str, Any] = {}
        self._ttl: dict[str, float] = {}
        self._lists: dict[str, list] = {}
        self._streams: dict[str, list] = {}
        self._pubsub_log: list[tuple] = []

    # ── helpers ────────────────────────────────────────────────────────────

    def _chk_ttl(self, key: str) -> None:
        exp = self._ttl.get(key)
        if exp is not None and _time_module.monotonic() > exp:
            self._kv.pop(key, None)
            self._ttl.pop(key, None)

    # ── primitives ─────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Any:
        self._chk_ttl(key)
        return self._kv.get(key)

    async def set(self, key: str, value: Any,
                  ex: int | None = None, px: int | None = None,
                  nx: bool = False) -> bool:
        self._chk_ttl(key)
        if nx and key in self._kv:
            return False
        self._kv[key] = value
        if ex is not None:
            self._ttl[key] = _time_module.monotonic() + ex
        elif px is not None:
            self._ttl[key] = _time_module.monotonic() + px / 1000.0
        else:
            self._ttl.pop(key, None)
        return True

    async def setex(self, key: str, ttl: int, value: Any) -> bool:
        return await self.set(key, value, ex=ttl)

    async def exists(self, *keys: str) -> int:
        count = 0
        for k in keys:
            self._chk_ttl(k)
            if k in self._kv:
                count += 1
        return count

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if self._kv.pop(k, None) is not None:
                removed += 1
            self._ttl.pop(k, None)
        return removed

    async def expire(self, key: str, ttl: int) -> bool:
        if key in self._kv:
            self._ttl[key] = _time_module.monotonic() + ttl
            return True
        return False

    async def incr(self, key: str) -> int:
        return await self.incrby(key, 1)

    async def incrby(self, key: str, amount: int) -> int:
        self._chk_ttl(key)
        val = int(self._kv.get(key, 0)) + amount
        self._kv[key] = str(val)
        return val

    async def decrby(self, key: str, amount: int) -> int:
        self._chk_ttl(key)
        val = max(0, int(self._kv.get(key, 0)) - amount)
        self._kv[key] = str(val)
        return val

    # ── scan / keys ────────────────────────────────────────────────────────

    async def keys(self, pattern: str = "*") -> list:
        import fnmatch
        return [k for k in self._kv if fnmatch.fnmatch(k, pattern)]

    async def scan_iter(self, match: str = "*", count: int = 100):
        import fnmatch
        for k in list(self._kv.keys()):
            if fnmatch.fnmatch(k, match):
                yield k

    # ── pub/sub ────────────────────────────────────────────────────────────

    async def publish(self, channel: str, message: Any) -> int:
        self._pubsub_log.append((channel, message))
        return 0

    # ── listes ─────────────────────────────────────────────────────────────

    async def lpush(self, key: str, *values: Any) -> int:
        lst = self._lists.setdefault(key, [])
        for v in reversed(values):
            lst.insert(0, v)
        return len(lst)

    async def rpush(self, key: str, *values: Any) -> int:
        lst = self._lists.setdefault(key, [])
        lst.extend(values)
        return len(lst)

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        lst = self._lists.get(key, [])
        self._lists[key] = lst[start:(end + 1 if end >= 0 else None)]
        return True

    async def lrange(self, key: str, start: int, end: int) -> list:
        lst = self._lists.get(key, [])
        return lst[start:(end + 1 if end >= 0 else None)]

    async def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    # ── streams ────────────────────────────────────────────────────────────

    async def xadd(self, name: str, fields: dict, id: str = "*",
                   maxlen: int | None = None, approximate: bool = False) -> bytes:
        entry_id = f"{int(_time_module.time() * 1000)}-0".encode()
        self._streams.setdefault(name, []).append({"id": entry_id, "fields": fields})
        if maxlen and len(self._streams[name]) > maxlen:
            self._streams[name] = self._streams[name][-maxlen:]
        return entry_id

    async def xlen(self, name: str) -> int:
        return len(self._streams.get(name, []))

    async def xgroup_create(self, name: str, groupname: str,
                             id: str = "0", mkstream: bool = False) -> bool:
        return True

    async def xreadgroup(self, groupname: str, consumername: str,
                         streams: dict, count: int | None = None,
                         block: int | None = None) -> list:
        return []

    async def xack(self, name: str, groupname: str, *ids: Any) -> int:
        return len(ids)

    async def xautoclaim(self, name: str, groupname: str, consumername: str,
                         min_idle_time: int, start_id: str = "0-0",
                         count: int | None = None) -> tuple:
        return ("0-0", [])

    async def xpending(self, name: str, groupname: str,
                       min: str | None = None, max: str | None = None,
                       count: int | None = None) -> Any:
        return {"pending": 0, "min": None, "max": None, "consumers": []}

    # ── pipeline ───────────────────────────────────────────────────────────

    def pipeline(self, transaction: bool = True) -> _AsyncMemPipeline:
        return _AsyncMemPipeline(self)

    # ── context manager ────────────────────────────────────────────────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass

    async def aclose(self) -> None:
        pass

    async def close(self) -> None:
        pass


class _AsyncMemPipeline:
    """Pipeline Redis in-memory — empile et exécute séquentiellement."""

    def __init__(self, redis: _AsyncMemRedis) -> None:
        self._r = redis
        self._q: list[tuple[str, tuple, dict]] = []

    def _enq(self, method: str, *args: Any, **kwargs: Any) -> _AsyncMemPipeline:
        self._q.append((method, args, kwargs))
        return self

    def set(self, key: str, value: Any,
            ex: int | None = None, nx: bool = False) -> _AsyncMemPipeline:
        return self._enq("set", key, value, ex=ex, nx=nx)

    def get(self, key: str) -> _AsyncMemPipeline:
        return self._enq("get", key)

    def setex(self, key: str, ttl: int, value: Any) -> _AsyncMemPipeline:
        return self._enq("setex", key, ttl, value)

    def decrby(self, key: str, amount: int) -> _AsyncMemPipeline:
        return self._enq("decrby", key, amount)

    def incrby(self, key: str, amount: int) -> _AsyncMemPipeline:
        return self._enq("incrby", key, amount)

    def incr(self, key: str) -> _AsyncMemPipeline:
        return self._enq("incr", key)

    def expire(self, key: str, ttl: int) -> _AsyncMemPipeline:
        return self._enq("expire", key, ttl)

    def delete(self, *keys: str) -> _AsyncMemPipeline:
        return self._enq("delete", *keys)

    def lpush(self, key: str, *values: Any) -> _AsyncMemPipeline:
        return self._enq("lpush", key, *values)

    def exists(self, *keys: str) -> _AsyncMemPipeline:
        return self._enq("exists", *keys)

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for method_name, args, kwargs in self._q:
            fn = getattr(self._r, method_name)
            results.append(await fn(*args, **kwargs))
        self._q.clear()
        return results

    async def __aenter__(self) -> _AsyncMemPipeline:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass


@pytest.fixture(scope="session", autouse=True)
def mock_redis_globally():
    """Substitue Redis par un backend in-memory pour toute la session de tests.

    Patch les 4 points d'entrée Redis du projet :
      • services.redis_lock.get_redis   (sync, retourne le client async)
      • services.redis_lock._redis_client  (singleton global — court-circuit)
      • services.idempotency.get_redis  (wrapper dynamique)
      • lib.redis_client.get_redis      (async, pool séparé)

    Les tests qui patchent Redis localement (with patch(...):) continuent de
    fonctionner — leur patch local surcharge temporairement ce mock de session.
    """
    mem = _AsyncMemRedis()
    _patches: list[Any] = []

    def _start(target: str, **kwargs: Any) -> None:
        try:
            p = patch(target, **kwargs)
            p.start()
            _patches.append(p)
        except Exception:
            pass  # module non importé encore — ignoré silencieusement

    # services.redis_lock : point d'entrée principal (sync → retourne client)
    _start("services.redis_lock.get_redis", return_value=mem)
    # Court-circuiter le singleton pour que get_redis() ne tente pas de créer
    # une vraie connexion si le module est importé après le patch.
    _start("services.redis_lock._redis_client", new=mem)

    # services.idempotency expose son propre get_redis() comme wrapper
    _start("services.idempotency.get_redis", return_value=mem)

    # lib.redis_client.get_redis est async
    _start("lib.redis_client.get_redis", new=AsyncMock(return_value=mem))
    # Court-circuiter le pool asyncio
    _start("lib.redis_client._pool", new=object())

    yield mem

    for p in reversed(_patches):
        try:
            p.stop()
        except Exception:
            pass


@pytest.fixture(scope="session", autouse=True)
def mock_celery_globally():
    """Force Celery en mode eager (synchrone, sans broker) pour les tests.

    Quand task_always_eager=True, appeler .delay() ou .apply_async() exécute
    la tâche dans le même process Python sans contacter Redis comme broker.
    task_eager_propagates=True remonte les exceptions pour ne pas masquer les
    bugs.

    Si Celery n'est pas installé ou si celery_app est None (ImportError),
    la fixture est un no-op.
    """
    try:
        from services.celery_app import celery_app as _app
        if _app is None:
            yield
            return
        _app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True,
        )
    except Exception:
        pass
    yield


# ═══════════════════════════════════════════════════════════════════════════════
# PASSE 2 — Mock global OpenAI (élimine les AuthenticationError 401 en CI)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Problème : avec task_always_eager=True (Celery eager mode), les tâches
# s'exécutent synchronement. Certaines appellent services.openai_resolver,
# qui crée un AsyncOpenAI(api_key=settings.OPENAI_API_KEY). La clé de test
# ("sk-test-...") est rejetée par api.openai.com → AuthenticationError 401.
#
# mock_third_party_services patche httpx.AsyncClient mais OpenAI SDK
# conserve son propre client httpx instancié à la création du client.
# Il faut patcher directement les fonctions de résolution OpenAI.
#
# Fix :
#   mock_openai_globally (session, autouse) — patch :
#     • services.openai_resolver.get_platform_client
#     • services.openai_resolver.resolve_openai_client
#     • openai.AsyncOpenAI (pour les imports directs dans services/)
#
# Le mock retourne un objet qui implémente l'interface SDK officielle
# (client.chat.completions.create → coroutine → objet avec .choices).
# ═══════════════════════════════════════════════════════════════════════════════

class _MockOpenAICompletion:
    """Simule openai.types.chat.ChatCompletion."""
    class _Choice:
        class _Message:
            role = "assistant"
            content = "Test mock response"
        message = _Message()
        finish_reason = "stop"
        index = 0

    class _Usage:
        prompt_tokens = 5
        completion_tokens = 5
        total_tokens = 10

    id = "chatcmpl-test-mock"
    object = "chat.completion"
    model = "gpt-4o-mini"
    choices = [_Choice()]
    usage = _Usage()


class _MockOpenAIEmbedding:
    """Simule openai.types.CreateEmbeddingResponse."""
    class _EmbeddingData:
        embedding = [0.001] * 1536
        index = 0
        object = "embedding"
    data = [_EmbeddingData()]
    class _Usage:
        prompt_tokens = 4
        total_tokens = 4
    usage = _Usage()
    model = "text-embedding-ada-002"


class _MockAsyncOpenAIClient:
    """Simule openai.AsyncOpenAI — interface SDK officielle."""

    class _Completions:
        async def create(self, *args: Any, **kwargs: Any) -> _MockOpenAICompletion:
            return _MockOpenAICompletion()

    class _Chat:
        def __init__(self) -> None:
            self.completions = _MockAsyncOpenAIClient._Completions()

    class _Embeddings:
        async def create(self, *args: Any, **kwargs: Any) -> _MockOpenAIEmbedding:
            return _MockOpenAIEmbedding()

    class _Moderation:
        async def create(self, *args: Any, **kwargs: Any) -> Any:
            class _Result:
                id = "modr-test"
                results = [MagicMock(flagged=False)]
            return _Result()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.chat = _MockAsyncOpenAIClient._Chat()
        self.embeddings = _MockAsyncOpenAIClient._Embeddings()
        self.moderations = _MockAsyncOpenAIClient._Moderation()

    async def __aenter__(self) -> _MockAsyncOpenAIClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass


@pytest.fixture(scope="session", autouse=True)
def mock_openai_globally():
    """Patche globalement le client OpenAI pour toute la session de tests.

    Empêche les appels réseau réels à api.openai.com quand Celery eager-mode
    exécute les tâches synchronement (AuthenticationError 401 sinon).

    Points patchés :
      • services.openai_resolver.get_platform_client → retourne un mock SDK
      • services.openai_resolver.resolve_openai_client → coroutine → mock SDK
      • openai.AsyncOpenAI → remplacé par _MockAsyncOpenAIClient
    """
    _mock_client = _MockAsyncOpenAIClient()

    async def _fake_resolve(*args: Any, **kwargs: Any) -> _MockAsyncOpenAIClient:
        return _mock_client

    _patches: list[Any] = []

    def _start(target: str, **kwargs: Any) -> None:
        try:
            p = patch(target, **kwargs)
            p.start()
            _patches.append(p)
        except Exception:
            pass

    _start("services.openai_resolver.get_platform_client", return_value=_mock_client)
    _start("services.openai_resolver.resolve_openai_client", new=_fake_resolve)
    _start("openai.AsyncOpenAI", new=_MockAsyncOpenAIClient)
    # Patch aussi les imports directs dans llm_gateway.py
    _start("services.llm_gateway.AsyncOpenAI", new=_MockAsyncOpenAIClient)

    yield _mock_client

    for p in reversed(_patches):
        try:
            p.stop()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# PASSE 2 — Fixture benchmark de repli (pytest-benchmark optionnel)
# ═══════════════════════════════════════════════════════════════════════════════
#
# tests/load/test_tenant_middleware_latency.py::test_tenant_middleware_benchmark
# demande la fixture `benchmark` (fournie par pytest-benchmark). Si le package
# n'est pas installé, pytest lève "fixture 'benchmark' not found" AVANT
# d'exécuter le corps du test — le pytest.skip() à l'intérieur n'est jamais
# atteint.
#
# Fix : on fournit une fixture `benchmark` de repli (no-op) qui ne s'active que
# si pytest-benchmark n'est pas installé. Si pytest-benchmark est installé, sa
# fixture a la priorité (les fixtures de plugin ont la priorité sur conftest.py).
# ═══════════════════════════════════════════════════════════════════════════════

def _is_pytest_benchmark_installed() -> bool:
    try:
        import pytest_benchmark  # noqa: F401
        return True
    except ImportError:
        return False


if not _is_pytest_benchmark_installed():
    @pytest.fixture
    def benchmark():
        """Fixture benchmark de repli quand pytest-benchmark n'est pas installé.

        Exécute la fonction sans mesure de performance.
        """
        def _runner(func, *args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)
        return _runner
