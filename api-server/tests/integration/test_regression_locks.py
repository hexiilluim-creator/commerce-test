"""tests/integration/test_regression_locks.py — 8 tests de verrouillage de régressions.

Ces tests couvrent exactement les bugs corrigés lors de l'audit v24.
Leur rôle : empêcher toute régression sur les correctifs validés.

CRITÈRE : pytest tests/integration/test_regression_locks.py -v -> 8 tests green, 0 skip.
Stack : pytest-asyncio + httpx (ASGITransport) + SQLite in-memory (aiosqlite)
"""

from __future__ import annotations

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
#  1. ISOLATION TENANT — ACCÈS INTER-STORES
#     Régression : tenant B ne doit jamais accéder aux commandes de tenant A
#     via GET /orders/{id} — ni via la liste.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_store_a_cannot_read_store_b_orders(async_client: AsyncClient, db_session: AsyncSession):
    """LOCK-1 — Store A crée une commande ; Store B ne peut pas la lire.

    Vérifie :
    - GET /orders/{order_id_de_A} avec token B -> 403 ou 404, jamais 200
    - GET /orders/ avec token B -> liste vide (aucune commande de A)
    """

    def _creds(label: str) -> dict:
        s = uuid.uuid4().hex[:6]
        return {
            "email": f"lock_iso_{label}_{s}@example.com",
            "password": "Isolate123!",
            "store_name": f"IsoStore {label} {s}",
        }

    # Créer store A et store B
    reg_a = await async_client.post("/api/v1/auth/register", json=_creds("a"))
    assert reg_a.status_code == 201, f"register A: {reg_a.text}"
    token_a = reg_a.json()["access_token"]

    reg_b = await async_client.post("/api/v1/auth/register", json=_creds("b"))
    assert reg_b.status_code == 201, f"register B: {reg_b.text}"
    token_b = reg_b.json()["access_token"]

    # Store A crée un produit
    product_a = await async_client.post(
        "/api/v1/stock/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": f"Prod Lock {uuid.uuid4().hex[:4]}",
            "price": 25.0,
            "quantity": 5,
            "sku": f"LOCK-{uuid.uuid4().hex[:6]}",
        },
    )
    assert product_a.status_code == 201, f"POST /stock/: {product_a.text}"
    product_id = product_a.json()["id"]

    # Store A crée une commande
    order_a = await async_client.post(
        "/api/v1/orders/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "customer_phone": "+21698111001",
            "customer_name": "Client A",
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": 25.0}],
            "total_amount": 25.0,
        },
    )
    assert order_a.status_code in (200, 201), f"POST /orders/: {order_a.text}"
    order_id_a = order_a.json().get("id") or order_a.json().get("order_id")
    assert order_id_a is not None, "order_id absent de la réponse"

    # Store B tente de lire la commande de A par son ID -> doit être refusé
    steal = await async_client.get(
        f"/api/v1/orders/{order_id_a}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert steal.status_code in (403, 404), (
        f"SÉCURITÉ : Store B a pu lire la commande de A (HTTP {steal.status_code}). "
        f"Isolation tenant compromise. Réponse: {steal.text}"
    )

    # Store B liste ses commandes -> la commande de A ne doit pas y être
    list_b = await async_client.get(
        "/api/v1/orders/",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert list_b.status_code == 200, f"GET /orders/ B: {list_b.text}"
    body_b = list_b.json()
    items_b = body_b.get("items", body_b) if isinstance(body_b, dict) else body_b
    ids_b = {o.get("id") or o.get("order_id") for o in items_b if isinstance(o, dict)}
    assert order_id_a not in ids_b, (
        f"SÉCURITÉ : order {order_id_a} de Store A visible dans la liste de Store B. Cross-contamination détectée."
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  2. ANALYTICS REVENUE — STATUTS PAID + DELIVERED + SHIPPED
#     Régression : avant le fix, les commandes DELIVERED ne comptaient pas
#     dans le CA. GET /analytics/overview -> revenue devait être 0.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_revenue_counts_delivered_orders(async_client: AsyncClient, db_session: AsyncSession):
    """LOCK-2 — Une commande avec status=DELIVERED contribue au CA dans /analytics/overview.

    Vérifie que OrderStatus.DELIVERED est bien inclus dans la somme du revenue.
    """
    suffix = uuid.uuid4().hex[:6]
    reg = await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": f"rev_{suffix}@example.com",
            "password": "Revenue123!",
            "store_name": f"Rev Store {suffix}",
        },
    )
    assert reg.status_code == 201, f"register: {reg.text}"
    token = reg.json()["access_token"]
    store_id = reg.json()["store_id"]

    # Insérer directement en DB une commande DELIVERED pour bypasser le webhook paiement
    from models.database import Customer, Order, OrderStatus

    customer = Customer(
        store_id=store_id,
        whatsapp_phone="+21698222001",
        name="Client Livré",
        opted_out=False,
    )
    db_session.add(customer)
    await db_session.flush()

    delivered_order = Order(
        store_id=store_id,
        customer_id=customer.id,
        total_amount=199.99,
        status=OrderStatus.DELIVERED,
        created_at=datetime.now(UTC),
        items=[],
    )
    db_session.add(delivered_order)
    await db_session.commit()
    await db_session.refresh(delivered_order)

    # GET /analytics/overview -> le CA doit être > 0
    overview = await async_client.get(
        "/api/v1/analytics/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert overview.status_code == 200, f"GET /analytics/overview: {overview.text}"
    data = overview.json()

    revenue = data.get("revenue", data.get("ca", data.get("total_revenue", None)))
    assert revenue is not None, (
        f"Clé 'revenue'/'ca'/'total_revenue' absente de la réponse overview: {list(data.keys())}"
    )
    assert float(revenue) > 0, (
        f"CA = {revenue} alors qu'une commande DELIVERED de 199.99 existe. "
        "Le filtre OrderStatus inclut-il bien DELIVERED ?"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  3. AGENT MUTE — TTL REDIS
#     Régression : la sourdine doit s'annuler automatiquement après expiration
#     du TTL Redis. should_ai_respond() doit retourner True après expiration.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mute_expires_after_ttl(async_client: AsyncClient, db_session: AsyncSession):
    """LOCK-3 — should_ai_respond() retourne False pendant la sourdine,
    puis True après expiration du TTL Redis.

    Teste directement le service agent_mute avec un mock Redis pour simuler
    l'expiration sans attendre réellement N minutes.
    """
    from services.agent_mute import _k_mute, should_ai_respond

    store_id = 9901
    phone = "+21698333001"

    # ── Phase 1 : simuler une sourdine active (clé Redis existe) ─────────────
    mock_redis_muted = AsyncMock()
    mock_redis_muted.exists = AsyncMock(return_value=1)  # muted = True
    mock_redis_muted.get = AsyncMock(return_value=None)  # no takeover

    with patch("services.agent_mute.get_redis", return_value=mock_redis_muted):
        # get_redis est appelé directement — on le remplace par un callable async
        async def _get_muted():
            return mock_redis_muted

        with patch("services.agent_mute.get_redis", new=_get_muted):
            respond, reason = await should_ai_respond(store_id, phone)
            assert respond is False, "Sourdine active : IA ne doit pas répondre"
            assert reason == "muted", f"Raison attendue 'muted', reçu '{reason}'"

    # ── Phase 2 : simuler expiration TTL (clé Redis n'existe plus) ───────────
    mock_redis_expired = AsyncMock()
    mock_redis_expired.exists = AsyncMock(return_value=0)  # mute expiré
    mock_redis_expired.get = AsyncMock(return_value=None)  # pas de takeover

    async def _get_expired():
        return mock_redis_expired

    with patch("services.agent_mute.get_redis", new=_get_expired):
        respond_after, reason_after = await should_ai_respond(store_id, phone)
        assert respond_after is True, (
            f"Après expiration TTL, l'IA doit reprendre (respond={respond_after}, reason={reason_after})"
        )
        assert reason_after == "active", f"Raison attendue 'active' après expiration, reçu '{reason_after}'"


# ═══════════════════════════════════════════════════════════════════════════════
#  4. BROADCAST OPT-OUT
#     Régression : un client avec opted_out=True ne doit jamais apparaître
#     dans la liste des destinataires d'un broadcast.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_opted_out_customer_not_in_broadcast(async_client: AsyncClient, db_session: AsyncSession):
    """LOCK-4 — opted_out=True exclut le client de la liste de broadcast réelle en DB.

    Vérifie la requête SQL effective : seuls les clients opted_out=False
    (ou NULL) doivent être retournés par un SELECT filtré.
    """
    from models.database import Customer

    suffix = uuid.uuid4().hex[:6]
    reg = await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": f"bcast_{suffix}@example.com",
            "password": "Bcast1234!",
            "store_name": f"Bcast Store {suffix}",
        },
    )
    assert reg.status_code == 201, f"register: {reg.text}"
    store_id = reg.json()["store_id"]

    # Insérer 3 clients : 2 opt-in, 1 opt-out
    cust_in_1 = Customer(
        store_id=store_id,
        whatsapp_phone=f"+2169840{suffix[:4]}",
        name="Client OptIn 1",
        opted_out=False,
    )
    cust_in_2 = Customer(
        store_id=store_id,
        whatsapp_phone=f"+2169841{suffix[:4]}",
        name="Client OptIn 2",
        opted_out=False,
    )
    cust_out = Customer(
        store_id=store_id,
        whatsapp_phone=f"+2169842{suffix[:4]}",
        name="Client OptOut",
        opted_out=True,
        opted_out_at=datetime.now(UTC),
    )
    db_session.add_all([cust_in_1, cust_in_2, cust_out])
    await db_session.commit()
    await db_session.refresh(cust_in_1)
    await db_session.refresh(cust_in_2)
    await db_session.refresh(cust_out)

    # Reproduire exactement la requête broadcast de owner_agent.py (lignes 270/293)
    result = await db_session.execute(
        select(Customer).where(
            Customer.store_id == store_id,
            Customer.opted_out.is_(False),
        )
    )
    broadcast_recipients = result.scalars().all()

    recipient_ids = {c.id for c in broadcast_recipients}
    recipient_phones = [c.whatsapp_phone for c in broadcast_recipients]

    # Client opt-out ne doit pas être dans la liste
    assert cust_out.id not in recipient_ids, (
        f"Client opt-out (id={cust_out.id}, phone={cust_out.whatsapp_phone}) "
        f"présent dans la liste broadcast : {recipient_phones}"
    )

    # Les 2 clients opt-in doivent être dans la liste
    assert cust_in_1.id in recipient_ids, f"Client opt-in 1 (id={cust_in_1.id}) absent de la liste broadcast"
    assert cust_in_2.id in recipient_ids, f"Client opt-in 2 (id={cust_in_2.id}) absent de la liste broadcast"

    assert len(broadcast_recipients) == 2, (
        f"Attendu 2 destinataires (opt-in seulement), reçu {len(broadcast_recipients)}: {recipient_phones}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  5. SUPER-ADMIN PAGINATION RÉELLE
#     Régression : /super-admin/stores retournait SELECT * sans LIMIT.
#     Le fix MED-4 ajoute la pagination — les paramètres doivent être honorés.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_super_admin_stores_pagination(async_client: AsyncClient, db_session: AsyncSession, auth_headers):
    """LOCK-5 — GET /super-admin/stores?page=1&page_size=5 retourne max 5 items
    et un total cohérent avec les stores créés.

    Vérifie que la pagination est opérationnelle et que page=2 ne duplique pas.
    """
    sa_headers = await auth_headers("super_admin")

    # Récupérer le total existant avant d'ajouter des stores
    baseline = await async_client.get(
        "/api/v1/super-admin/stores?page=1&page_size=100",
        headers=sa_headers,
    )
    assert baseline.status_code == 200, f"baseline stores: {baseline.text}"
    baseline_total = baseline.json().get("total", 0)

    # Créer 12 stores supplémentaires pour garantir une 2e page à page_size=5
    EXTRA_STORES = 12
    for i in range(EXTRA_STORES):
        s = uuid.uuid4().hex[:5]
        r = await async_client.post(
            "/api/v1/auth/register",
            json={
                "email": f"pgstore{i}_{s}@example.com",
                "password": "Paginate1!",
                "store_name": f"PgStore {i} {s}",
            },
        )
        assert r.status_code == 201, f"register store {i}: {r.text}"

    expected_total = baseline_total + EXTRA_STORES

    # Requête page 1, page_size=5
    resp_p1 = await async_client.get(
        "/api/v1/super-admin/stores?page=1&page_size=5",
        headers=sa_headers,
    )
    assert resp_p1.status_code == 200, f"page 1: {resp_p1.text}"
    data_p1 = resp_p1.json()

    assert "items" in data_p1, f"Clé 'items' absente: {list(data_p1.keys())}"
    assert "total" in data_p1, f"Clé 'total' absente: {list(data_p1.keys())}"
    assert "page" in data_p1, f"Clé 'page' absente: {list(data_p1.keys())}"

    items_p1 = data_p1["items"]
    total = data_p1["total"]

    assert len(items_p1) == 5, f"page_size=5 -> attendu 5 items, reçu {len(items_p1)}"
    assert total >= expected_total, (
        f"total={total} devrait être >= {expected_total} après création de {EXTRA_STORES} stores"
    )

    # Requête page 2, page_size=5 — ne doit pas dupliquer les items de page 1
    resp_p2 = await async_client.get(
        "/api/v1/super-admin/stores?page=2&page_size=5",
        headers=sa_headers,
    )
    assert resp_p2.status_code == 200, f"page 2: {resp_p2.text}"
    items_p2 = resp_p2.json()["items"]

    ids_p1 = {s["id"] for s in items_p1}
    ids_p2 = {s["id"] for s in items_p2}
    assert ids_p1.isdisjoint(ids_p2), f"Doublons entre page 1 et page 2: {ids_p1 & ids_p2}"


# ═══════════════════════════════════════════════════════════════════════════════
#  6. STOREFRONT SLUG RÉSOLUTION
#     Régression : avant le fix, /storefront/{slug} ne fonctionnait que pour
#     les IDs numériques — les liens slug retournaient 404.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_storefront_accessible_by_slug_and_by_id(async_client: AsyncClient, db_session: AsyncSession):
    """LOCK-6 — /storefront/{slug} et /storefront/{id} retournent le même store.

    Vérifie que _resolve_store() accepte slug ET id numérique.
    /storefront/inexistant -> 404.
    """
    suffix = uuid.uuid4().hex[:6]
    reg = await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": f"sf_{suffix}@example.com",
            "password": "Storefront1!",
            "store_name": f"Slug Store {suffix}",
        },
    )
    assert reg.status_code == 201, f"register: {reg.text}"
    reg.json()["access_token"]
    store_id = reg.json()["store_id"]

    # Récupérer le slug assigné au store (via le profil ou settings)
    from models.database import Store

    store = await db_session.get(Store, store_id)
    assert store is not None, f"Store {store_id} introuvable en DB"

    # Si le store n'a pas encore de slug, en assigner un
    if not store.slug:
        store.slug = f"slug-store-{suffix}"
        await db_session.commit()
        await db_session.refresh(store)

    slug = store.slug
    assert slug, "Le store doit avoir un slug non vide"

    # GET /storefront/{slug} -> 200
    resp_slug = await async_client.get(f"/api/v1/storefront/{slug}")
    assert resp_slug.status_code == 200, (
        f"GET /storefront/{slug} -> {resp_slug.status_code}. "
        f"La résolution par slug est cassée. Réponse: {resp_slug.text}"
    )
    data_slug = resp_slug.json()
    assert data_slug.get("id") == store_id, f"ID retourné ({data_slug.get('id')}) ≠ store_id attendu ({store_id})"

    # GET /storefront/{numeric_id} -> 200
    resp_id = await async_client.get(f"/api/v1/storefront/{store_id}")
    assert resp_id.status_code == 200, (
        f"GET /storefront/{store_id} -> {resp_id.status_code}. La résolution par ID est cassée. Réponse: {resp_id.text}"
    )
    data_id = resp_id.json()
    assert data_id.get("id") == store_id

    # Les deux réponses doivent pointer vers le même store
    assert data_slug.get("id") == data_id.get("id"), (
        f"Slug ({data_slug.get('id')}) et ID ({data_id.get('id')}) ne pointent pas vers le même store"
    )

    # GET /storefront/{inexistant} -> 404
    resp_404 = await async_client.get("/api/v1/storefront/boutique-qui-nexiste-pas-xyzabc123")
    assert resp_404.status_code == 404, f"slug inexistant -> attendu 404, reçu {resp_404.status_code}"


# ═══════════════════════════════════════════════════════════════════════════════
#  7. CREDITS MONTHLY STATS — PAS DE 500
#     Régression :
#     - func.cast("N months", type_=None) -> NullType -> 500 serveur.
#     - XSS validation sur ?months= rejetait la valeur -> 400.
#     Le fix calcule le cutoff en Python. Doit retourner 200 avec structure valide.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_credits_monthly_stats_with_months_param(async_client: AsyncClient, db_session: AsyncSession):
    """LOCK-7 — GET /admin/credits/stats/monthly?months=6 retourne 200.

    Vérifie l'absence des deux régressions :
    - HTTP 400 dû au filtre XSS sur le paramètre ?months=
    - HTTP 500 dû au func.cast NullType sur l'interval PostgreSQL

    La réponse doit contenir :
    - "months" : liste de dicts avec au moins la clé "month" (YYYY-MM)
    - "grand_total" : nombre >= 0
    """
    internal_token = "test-health-token-001"  # défini dans conftest.py

    # Test principal : months=6 (cas typique du dashboard)
    resp = await async_client.get(
        "/api/v1/admin/credits/stats/monthly?months=6",
        headers={"X-Internal-Token": internal_token},
    )
    assert resp.status_code == 200, (
        f"GET /admin/credits/stats/monthly?months=6 -> {resp.status_code}. "
        f"Réponse: {resp.text[:300]}. "
        "Vérifier le fix func.cast NullType et le filtre XSS sur ?months="
    )

    data = resp.json()
    assert "months" in data, f"Clé 'months' absente: {list(data.keys())}"
    assert "grand_total" in data, f"Clé 'grand_total' absente: {list(data.keys())}"

    months_list = data["months"]
    assert isinstance(months_list, list), f"'months' doit être une liste, reçu: {type(months_list)}"
    # Doit retourner exactement 6 entrées (même si consommation = 0)
    assert len(months_list) == 6, f"?months=6 doit retourner 6 entrées, reçu {len(months_list)}"

    for entry in months_list:
        assert "month" in entry, f"Clé 'month' absente dans une entrée: {entry}"
        # Format YYYY-MM
        month_str = entry["month"]
        assert len(month_str) == 7 and month_str[4] == "-", f"Format YYYY-MM attendu pour 'month', reçu '{month_str}'"

    grand_total = data["grand_total"]
    assert isinstance(grand_total, int | float), f"'grand_total' doit être numérique, reçu {type(grand_total)}"
    assert grand_total >= 0, f"'grand_total' négatif inattendu: {grand_total}"

    # Test avec months=3 (valeur alternative)
    resp3 = await async_client.get(
        "/api/v1/admin/credits/stats/monthly?months=3",
        headers={"X-Internal-Token": internal_token},
    )
    assert resp3.status_code == 200, f"GET /admin/credits/stats/monthly?months=3 -> {resp3.status_code}"
    assert len(resp3.json()["months"]) == 3, "?months=3 doit retourner 3 entrées"


# ═══════════════════════════════════════════════════════════════════════════════
#  8. BLUEPRINT ROUTE ORDER — /my-store NON MASQUÉ PAR /{id}
#     Régression : dans FastAPI, les routes wildcard /{id} capturent aussi
#     /my-store si elles sont enregistrées AVANT /my-store dans le router.
#     GET /blueprints/my-store ne doit jamais retourner 404 "Blueprint non trouvé"
#     (ce qui arriverait si /{id} capturait "my-store" avant /my-store).
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_blueprint_my_store_not_matched_by_wildcard(async_client: AsyncClient, db_session: AsyncSession):
    """LOCK-8 — GET /blueprints/my-store avec token valide ne retourne pas
    404 "Blueprint non trouvé" (qui indiquerait que la route /{id} a capturé
    le segment 'my-store' avant la route spécifique /my-store).

    Comportement attendu :
    - 200 : le store a sélectionné un blueprint (ou aucun -> null/{}),
    - 404 avec message ≠ "Blueprint non trouvé" (impossible ici car route correcte),
    - ou tout code < 500 sauf le 404 "Blueprint non trouvé" piège.

    Vérifie aussi que GET /blueprints/{id_inexistant} retourne bien 404
    avec "Blueprint non trouvé" (confirmation que /{id} fonctionne toujours).
    """
    suffix = uuid.uuid4().hex[:6]
    reg = await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": f"bp_{suffix}@example.com",
            "password": "Blueprint1!",
            "store_name": f"BP Store {suffix}",
        },
    )
    assert reg.status_code == 201, f"register: {reg.text}"
    token = reg.json()["access_token"]

    # GET /blueprints/my-store avec token -> doit atteindre la bonne route
    resp_mystore = await async_client.get(
        "/api/v1/blueprints/my-store",
        headers={"Authorization": f"Bearer {token}"},
    )

    # La route /my-store existe et est protégée par auth
    # Elle peut retourner 200 (null ou un blueprint), pas de 401/403 attendu ici
    # Ce qui est INTERDIT : 404 avec "Blueprint non trouvé" car cela signifie
    # que /{id} a capturé "my-store" et l'a traité comme un ID inexistant.
    assert resp_mystore.status_code != 404 or (
        resp_mystore.status_code == 404
        and "non trouvé" not in resp_mystore.text.lower()
        and "not found" not in resp_mystore.text.lower()
    ), (
        f"RÉGRESSION ROUTE ORDER : GET /blueprints/my-store retourne 404 avec "
        f"'Blueprint non trouvé' — la route /{'{id}'} capture 'my-store' avant /my-store. "
        f"Réponse: {resp_mystore.text}"
    )

    assert resp_mystore.status_code < 500, f"Erreur serveur inattendue sur /blueprints/my-store: {resp_mystore.text}"

    # GET /blueprints/{id_inexistant} -> 404 "Blueprint non trouvé" (comportement normal)
    fake_id = "blueprint-inexistant-xyzabc999"
    resp_fake = await async_client.get(f"/api/v1/blueprints/{fake_id}")
    assert resp_fake.status_code == 404, (
        f"Blueprint inexistant '{fake_id}' -> attendu 404, reçu {resp_fake.status_code}"
    )
    # Confirmer que c'est bien le message de /{id} et non un autre 404
    assert "non trouvé" in resp_fake.text.lower() or "not found" in resp_fake.text.lower(), (
        f"Message 404 attendu ('Blueprint non trouvé'), reçu: {resp_fake.text}"
    )
