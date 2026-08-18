"""tests/integration/test_security_billing_locks.py — 5 tests de verrouillage sécurité/billing.

Complète test_regression_locks.py en couvrant les zones à 0 tests réels identifiées par l'audit :
  - JWT middleware rejet HTTP réel (tokens expirés, forgés, manquants)
  - Blocage tenant quand abonnement inactif (is_active=False -> 403)
  - Paymee verify_payment (succès / échec / config manquante)
  - PII Redactor masquage effectif (téléphone, email, CIN)
  - Conversation memory court terme (store/load avec sérialisation JSON)

CRITÈRE : pytest tests/integration/test_security_billing_locks.py -v -> 5 tests green, 0 skip.
Stack : pytest-asyncio + httpx (ASGITransport) + SQLite in-memory (aiosqlite)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


# ═══════════════════════════════════════════════════════════════════════════════
#  1. JWT MIDDLEWARE — REJET RÉEL VIA HTTP
#     test_security_multitenant.py génère des tokens en isolation Python mais
#     ne les envoie jamais à une vraie route. Ce test corrige cela.
#
#     Vérifie que TenantMiddleware rejette correctement :
#       (a) token absent            -> 401
#       (b) token signé avec le mauvais secret -> 401
#       (c) token expiré            -> 401
#       (d) token valide sans store_id -> 401
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_jwt_middleware_real_http_rejection(
    async_client: AsyncClient, db_session: AsyncSession
):
    """LOCK-9 — TenantMiddleware rejette les tokens invalides sur une vraie route HTTP.

    GET /api/v1/auth/me est une route protégée simple, idéale pour tester
    les 4 variantes de token invalide sans effets de bord.
    """
    import jwt as jose

    jwt_secret = "test-secret-key-32chars-minimum!!"

    # ── (a) Pas de token du tout -> 401 ──────────────────────────────────────
    resp_no_token = await async_client.get("/api/v1/auth/me")
    assert resp_no_token.status_code == 401, (
        f"Sans token -> attendu 401, reçu {resp_no_token.status_code}. "
        "TenantMiddleware ne protège pas la route."
    )

    # ── (b) Token signé avec le mauvais secret -> 401 ─────────────────────────
    forged_payload = {
        "sub": "1",
        "store_id": 1,
        "role": "admin",
        "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
    }
    forged_token = jose.encode(forged_payload, "WRONG-SECRET-NOT-THE-REAL-ONE!!", algorithm="HS256")

    resp_forged = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {forged_token}"},
    )
    assert resp_forged.status_code == 401, (
        f"Token forgé (mauvais secret) -> attendu 401, reçu {resp_forged.status_code}. "
        "Signature vérifiée correctement ?"
    )

    # ── (c) Token expiré -> 401 ───────────────────────────────────────────────
    expired_payload = {
        "sub": "1",
        "store_id": 1,
        "role": "admin",
        "exp": (datetime.now(UTC) - timedelta(hours=2)).timestamp(),  # dans le passé
    }
    expired_token = jose.encode(expired_payload, jwt_secret, algorithm="HS256")

    resp_expired = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp_expired.status_code == 401, (
        f"Token expiré -> attendu 401, reçu {resp_expired.status_code}. "
        "L'expiration JWT n'est pas vérifiée."
    )

    # ── (d) Token valide mais sans store_id -> 401 ────────────────────────────
    no_store_payload = {
        "sub": "1",
        "role": "admin",
        # store_id absent intentionnellement
        "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
    }
    no_store_token = jose.encode(no_store_payload, jwt_secret, algorithm="HS256")

    resp_no_store = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {no_store_token}"},
    )
    assert resp_no_store.status_code == 401, (
        f"Token sans store_id -> attendu 401, reçu {resp_no_store.status_code}. "
        "Le claim store_id n'est pas validé."
    )

    # ── Contrôle positif : token valide -> 200 ────────────────────────────────
    suffix = uuid.uuid4().hex[:6]
    reg = await async_client.post("/api/v1/auth/register", json={
        "email": f"jwttest_{suffix}@example.com",
        "password": "JwtTest123!",
        "store_name": f"JWT Store {suffix}",
    })
    assert reg.status_code == 201
    valid_token = reg.json()["access_token"]

    resp_valid = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert resp_valid.status_code == 200, (
        f"Token valide -> attendu 200, reçu {resp_valid.status_code}. "
        f"Réponse: {resp_valid.text}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  2. BLOCAGE TENANT — ABONNEMENT INACTIF -> 403
#     Lorsqu'un store passe is_active=False (abonnement expiré, suspension),
#     toutes ses requêtes protégées doivent recevoir 403, jamais 200.
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_suspended_tenant_gets_403(
    async_client: AsyncClient, db_session: AsyncSession
):
    """LOCK-10 — store.is_active=False -> toutes les requêtes protégées -> 403.

    Simule la suspension d'un tenant (abonnement expiré, fraude, admin action).
    Le token est toujours valide (non expiré) mais le store est inactif.
    """
    from models.database import Store

    suffix = uuid.uuid4().hex[:6]
    reg = await async_client.post("/api/v1/auth/register", json={
        "email": f"suspend_{suffix}@example.com",
        "password": "Suspend123!",
        "store_name": f"Suspend Store {suffix}",
    })
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    store_id = reg.json()["store_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Vérifier que le store actif répond 200
    resp_active = await async_client.get("/api/v1/auth/me", headers=headers)
    assert resp_active.status_code == 200, (
        f"Store actif -> attendu 200 avant suspension, reçu {resp_active.status_code}"
    )

    # Suspendre le store directement en DB
    store = await db_session.get(Store, store_id)
    assert store is not None
    store.is_active = False
    store.suspended_reason = "Subscription expired — auto-suspended"
    await db_session.commit()

    # Toute requête protégée doit maintenant retourner 403
    resp_suspended = await async_client.get("/api/v1/auth/me", headers=headers)
    assert resp_suspended.status_code == 403, (
        f"Store suspendu (is_active=False) -> attendu 403, reçu {resp_suspended.status_code}. "
        f"Réponse: {resp_suspended.text}. "
        "TenantMiddleware vérifie-t-il store.is_active ?"
    )

    # Réactiver et vérifier le retour à 200
    store.is_active = True
    store.suspended_reason = None
    await db_session.commit()

    resp_reactivated = await async_client.get("/api/v1/auth/me", headers=headers)
    assert resp_reactivated.status_code == 200, (
        f"Store réactivé -> attendu 200, reçu {resp_reactivated.status_code}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  3. PAYMEE PROVIDER — VERIFY_PAYMENT (succès / échec / config manquante)
#     test_paymee_provider.py couvre create_payment_link mais pas verify_payment.
#     verify_payment est critique : c'est le chemin de confirmation paiement.
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_paymee_verify_payment_real_behavior(
    async_client: AsyncClient, db_session: AsyncSession
):
    """LOCK-11 — PaymeeProvider.verify_payment() retourne le bon statut selon la réponse API.

    Teste 3 scénarios :
      (a) Réponse SUCCESS  -> statut "paid"
      (b) Réponse FAILED   -> statut "failed"
      (c) Config manquante -> HTTPException 400
    """
    import importlib

    from fastapi import HTTPException

    pf = importlib.import_module("services.payment_factory")

    # ── (a) Réponse SUCCESS -> statut "paid" ──────────────────────────────────
    mock_resp_success = MagicMock()
    mock_resp_success.status_code = 200
    mock_resp_success.json.return_value = {
        "status": True,
        "data": {"status": "SUCCESS", "amount": 150.0}
    }
    with patch("services.payment_factory._http_request_with_retry", return_value=mock_resp_success):
        provider = pf.PaymeeProvider({"api_key": "test-api-key", "vendor_id": "12345"})
        result = await provider.verify_payment("token-abc123")

    assert result["status"] == "paid", (
        f"Réponse SUCCESS -> attendu 'paid', reçu '{result['status']}'"
    )
    assert result["provider"] == "paymee"

    # ── (b) Réponse FAILED -> statut "failed" ─────────────────────────────────
    mock_resp_failed = MagicMock()
    mock_resp_failed.status_code = 200
    mock_resp_failed.json.return_value = {
        "status": False,
        "data": {"status": "FAILED"}
    }
    with patch("services.payment_factory._http_request_with_retry", return_value=mock_resp_failed):
        result_failed = await provider.verify_payment("token-xyz456")

    assert result_failed["status"] == "failed", (
        f"Réponse FAILED -> attendu 'failed', reçu '{result_failed['status']}'"
    )

    # ── (c) Config manquante (pas d'api_key) -> HTTPException 400 ──────────────
    provider_no_config = pf.PaymeeProvider({})
    with pytest.raises(HTTPException) as exc_info:
        await provider_no_config.verify_payment("any-token")
    assert exc_info.value.status_code == 400, (
        f"Config manquante -> attendu HTTPException 400, reçu {exc_info.value.status_code}"
    )
    assert "api_key" in str(exc_info.value.detail).lower() or "non configuré" in str(exc_info.value.detail).lower(), (
        f"Message d'erreur inattendu : {exc_info.value.detail}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  4. PII REDACTOR — MASQUAGE EFFECTIF (RGPD)
#     test_pii_redactor.py a 0 tests réels. Ce test vérifie que les données
#     personnelles sont bien masquées avant d'atteindre les logs.
# ═══════════════════════════════════════════════════════════════════════════════

def test_pii_redactor_masks_sensitive_data():
    """LOCK-12 — PIIRedactorFilter masque téléphone, email et CIN dans les logs.

    Teste directement :
      - _redact_string() sur des patterns PII connus
      - PIIRedactorFilter.filter() modifie bien le LogRecord
      - install_pii_redactor() est idempotent (pas de double filtre)
    """
    from services.pii_redactor import (
        PIIRedactorFilter,
        _redact_string,
        install_pii_redactor,
    )

    # ── Téléphone tunisien (+216) ─────────────────────────────────────────────
    phone_tn = "+21698000123"
    result = _redact_string(f"Client a appelé depuis {phone_tn}")
    assert phone_tn not in result, (
        f"Numéro tunisien '{phone_tn}' non masqué. Résultat: '{result}'"
    )
    assert "[PHONE]" in result, f"Marqueur [PHONE] absent. Résultat: '{result}'"

    # ── Email ─────────────────────────────────────────────────────────────────
    email = "client.dupont@example.com"
    result_email = _redact_string(f"Confirmation envoyée à {email}")
    assert email not in result_email, (
        f"Email '{email}' non masqué. Résultat: '{result_email}'"
    )
    assert "[EMAIL]" in result_email, f"Marqueur [EMAIL] absent. Résultat: '{result_email}'"

    # ── CIN tunisien (8 chiffres) ─────────────────────────────────────────────
    cin = "12345678"
    result_cin = _redact_string(f"CIN du client : {cin}")
    assert cin not in result_cin, (
        f"CIN '{cin}' non masqué. Résultat: '{result_cin}'"
    )

    # ── Numéro de carte bancaire ──────────────────────────────────────────────
    card = "4111 1111 1111 1111"
    result_card = _redact_string(f"Paiement avec carte {card}")
    assert card not in result_card, (
        f"Numéro de carte '{card}' non masqué. Résultat: '{result_card}'"
    )
    assert "[CARD]" in result_card, f"Marqueur [CARD] absent. Résultat: '{result_card}'"

    # ── PIIRedactorFilter.filter() modifie le LogRecord ───────────────────────
    filt = PIIRedactorFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO,
        pathname="", lineno=0,
        msg=f"Webhook reçu de {phone_tn} pour {email}",
        args=(), exc_info=None,
    )
    result_filter = filt.filter(record)
    assert result_filter is True, "filter() doit retourner True (ne bloque pas le log)"
    assert phone_tn not in record.msg, (
        f"Téléphone '{phone_tn}' présent dans record.msg après filter(): '{record.msg}'"
    )
    assert email not in record.msg, (
        f"Email '{email}' présent dans record.msg après filter(): '{record.msg}'"
    )

    # ── install_pii_redactor() est idempotent ─────────────────────────────────
    root_logger = logging.getLogger()
    sum(
        1 for f in root_logger.filters if isinstance(f, PIIRedactorFilter)
    )
    install_pii_redactor()
    install_pii_redactor()  # appel double
    final_filter_count = sum(
        1 for f in root_logger.filters if isinstance(f, PIIRedactorFilter)
    )
    assert final_filter_count == 1, (
        f"install_pii_redactor() doit être idempotent — "
        f"attendu 1 filtre, reçu {final_filter_count} (doublons présents)"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  5. CONVERSATION MEMORY — PERSISTANCE COURT TERME (Redis)
#     test_conversation_memory.py a 0 tests réels. Ce test vérifie que
#     store_short_term() et load_short_term() sérialisent/désérialisent
#     correctement les données et que le TTL est honoré.
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_conversation_short_term_memory_store_and_load(
    async_client: AsyncClient, db_session: AsyncSession
):
    """LOCK-13 — store_short_term() persiste les données, load_short_term() les retrouve.

    Teste avec un mock Redis pour éviter la dépendance externe.
    Vérifie :
      - la clé Redis est correctement formée (mem:st:{store_id}:{customer_id})
      - les données sont sérialisées en JSON (setex appelé avec le bon payload)
      - load_short_term() désérialise et retourne le dict original
      - TTL = SHORT_TERM_TTL_SECONDS (14400 secondes = 4h)
      - load_short_term() retourne {} si la clé est absente (aucune exception)
    """
    from services.conversation_memory_service import (
        SHORT_TERM_TTL_SECONDS,
        _short_term_key,
        load_short_term,
        store_short_term,
    )

    store_id = 7001
    customer_id = 8001
    expected_key = _short_term_key(store_id, customer_id)

    # Vérifier la forme de la clé
    assert expected_key == f"mem:st:{store_id}:{customer_id}", (
        f"Clé Redis inattendue: '{expected_key}'"
    )

    # Données à persister
    memory_data = {
        "last_intent": "purchase_inquiry",
        "cart": [{"product_id": 42, "qty": 2}],
        "customer_name": "Ali Ben Salah",
        "objections": ["prix trop élevé"],
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # ── Simuler Redis pour store_short_term ──────────────────────────────────
    stored_key = None
    stored_ttl = None
    stored_value = None

    mock_redis = AsyncMock()

    async def mock_setex(key, ttl, value):
        nonlocal stored_key, stored_ttl, stored_value
        stored_key = key
        stored_ttl = ttl
        stored_value = value

    mock_redis.setex = mock_setex

    async def _get_mock_redis():
        return mock_redis

    with patch("services.conversation_memory_service._get_redis", new=_get_mock_redis):
        await store_short_term(store_id, customer_id, memory_data)

    # Vérifier la clé
    assert stored_key == expected_key, (
        f"Clé Redis stockée '{stored_key}' ≠ clé attendue '{expected_key}'"
    )

    # Vérifier le TTL
    assert stored_ttl == SHORT_TERM_TTL_SECONDS, (
        f"TTL stocké {stored_ttl}s ≠ SHORT_TERM_TTL_SECONDS {SHORT_TERM_TTL_SECONDS}s"
    )
    assert SHORT_TERM_TTL_SECONDS == 4 * 3600, (
        f"TTL attendu 4h (14400s), reçu {SHORT_TERM_TTL_SECONDS}s"
    )

    # Vérifier que la valeur est du JSON valide
    assert stored_value is not None, "Aucune valeur stockée dans Redis"
    parsed = json.loads(stored_value)
    assert parsed["last_intent"] == "purchase_inquiry"
    assert parsed["cart"][0]["product_id"] == 42

    # ── Simuler Redis pour load_short_term (clé présente) ────────────────────
    mock_redis_load = AsyncMock()
    mock_redis_load.get = AsyncMock(return_value=stored_value)

    async def _get_mock_redis_load():
        return mock_redis_load

    with patch("services.conversation_memory_service._get_redis", new=_get_mock_redis_load):
        loaded = await load_short_term(store_id, customer_id)

    assert loaded["last_intent"] == memory_data["last_intent"], (
        f"last_intent non préservé: attendu '{memory_data['last_intent']}', "
        f"reçu '{loaded.get('last_intent')}'"
    )
    assert loaded["cart"] == memory_data["cart"], (
        f"cart non préservé: {loaded.get('cart')}"
    )
    assert loaded["objections"] == memory_data["objections"], (
        f"objections non préservées: {loaded.get('objections')}"
    )

    # ── Simuler Redis clé absente -> retourne {} sans exception ───────────────
    mock_redis_empty = AsyncMock()
    mock_redis_empty.get = AsyncMock(return_value=None)

    async def _get_mock_redis_empty():
        return mock_redis_empty

    with patch("services.conversation_memory_service._get_redis", new=_get_mock_redis_empty):
        empty_result = await load_short_term(store_id, 9999)

    assert empty_result == {}, (
        f"Clé absente -> attendu {{}}, reçu {empty_result}"
    )
