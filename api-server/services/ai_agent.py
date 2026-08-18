"""
ai_agent.py — AI Sales Agent avec FSM conversation (P1)
=========================================================
États FSM:
  IDLE -> BROWSING -> PRODUCT_SHOWN -> AWAITING_CONFIRM
       -> AWAITING_DELIVERY -> ORDER_CREATED -> IDLE

Nouveautés P1:
  - Timeout automatique (conversation_timeout_min configurable par store)
  - ConversationLog: trace de chaque transition en DB
  - Post-paiement: message WA de confirmation automatique (déclenché par reconcile_payment)
  - handle_button_reply: boutons interactifs routés vers actions métier
  - _extract_delivery_info: extraction GPT des infos livraison
  - _create_order_from_state: création Order réelle en DB
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings

# ─── HIGH-12 FIX: Validation profondeur/taille du conversation_state ──────────
# AVANT: customer.conversation_state était chargé sans aucun contrôle.
# Un attaquant contrôlant les messages entrants pouvait injecter un JSON très
# profond, provoquant une récursion excessive lors de la sérialisation/parsing.
# CORRIGÉ: helper qui rejette les états malformés et les réinitialise à {}.
_STATE_MAX_BYTES = 50_000  # 50 KB max en JSON sérialisé
_STATE_MAX_DEPTH = 5  # profondeur max des dicts imbriqués


def _json_depth(obj: object, current: int = 0) -> int:
    """Calcule la profondeur maximale d'un objet JSON (dict ou list)."""
    if current > _STATE_MAX_DEPTH:
        return current  # court-circuit — déjà trop profond
    if isinstance(obj, dict):
        if not obj:
            return current + 1
        return max(_json_depth(v, current + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return current + 1
        return max(_json_depth(v, current + 1) for v in obj)
    return current


def _sanitize_conversation_state(raw_state: object, customer_id: int | None = None) -> dict:
    """Valide et assainit le conversation_state chargé depuis la DB.

    - Doit être un dict (ou None -> retourne {})
    - Taille JSON sérialisé ≤ 50 KB
    - Profondeur JSON ≤ 5 niveaux
    En cas de violation, loggue un warning et retourne {} pour réinitialiser la FSM.
    Note: utilise logging.getLogger() directement car ce module-level logger
    n'est pas encore assigné à ce stade de l'initialisation du module.
    """
    _log = logging.getLogger(__name__)
    if raw_state is None:
        return {}
    if not isinstance(raw_state, dict):
        _log.warning(
            "conversation_state invalide (type=%s) pour customer_id=%s — réinitialisation",
            type(raw_state).__name__,
            customer_id,
        )
        return {}
    try:
        serialized = json.dumps(raw_state, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        _log.warning(
            "conversation_state non-sérialisable pour customer_id=%s: %s — réinitialisation",
            customer_id,
            exc,
        )
        return {}
    if len(serialized) > _STATE_MAX_BYTES:
        _log.warning(
            "conversation_state trop grand (%d bytes > %d) pour customer_id=%s — réinitialisation",
            len(serialized),
            _STATE_MAX_BYTES,
            customer_id,
        )
        return {}
    depth = _json_depth(raw_state)
    if depth > _STATE_MAX_DEPTH:
        _log.warning(
            "conversation_state trop profond (depth=%d > %d) pour customer_id=%s — réinitialisation",
            depth,
            _STATE_MAX_DEPTH,
            customer_id,
        )
        return {}
    return raw_state


from models.database import (
    ConversationLog,
    Customer,
    Order,
    OrderStatus,
    Product,
    Store,
)
from services.embedding_search import find_best_match
from services.llm_gateway import chat as llm_chat
from services.vision_analyzer import analyze_whatsapp_image
from utils.whatsapp_client import WhatsAppClient

# BLOC 10 : le wa_client peut être soit WhatsAppClient, soit ChannelRouter
# Les deux exposent send_text() et send_product_card() — interface identique
AnyChannelClient = WhatsAppClient  # type alias pour la doc ; runtime accept tout objet compatible

logger = logging.getLogger(__name__)
# Réaffecter le logger dans _sanitize_conversation_state pour éviter le forward-reference
# (logger est défini ici, la fonction est définie plus haut mais jamais appelée avant ce point)


# ─── FSM States ───────────────────────────────────────────────────────────────
# ─── System prompt ────────────────────────────────────────────────────────────
class State:
    IDLE = "idle"
    BROWSING = "browsing"
    PRODUCT_SHOWN = "product_shown"
    AWAITING_CONFIRM = "awaiting_confirm"
    AWAITING_DELIVERY = "awaiting_delivery"
    ORDER_CREATED = "order_created"
    PAYMENT_PENDING = "payment_pending"  # ACTION 12: entre ORDER_CREATED et confirmation paiement
    WAITING_SUPPORT = "waiting_support"  # ACTION 12: escalade vers humain trackée dans FSM


def build_system_prompt(store: Store, customer: Customer) -> str:
    """ACTION 13 — Cross-session memory injectée dans le prompt."""
    lang = customer.language or getattr(store, "language", "fr") or "fr"
    lang_instruction = "Réponds en français." if lang == "fr" else "أجب باللغة العربية."
    custom = getattr(store, "ai_agent_prompt", "") or ""
    # HIGH-12 FIX: valider profondeur/taille avant tout accès
    state = _sanitize_conversation_state(customer.conversation_state, getattr(customer, "id", None))
    state_label = state.get("fsm_state", State.IDLE)

    # ACTION 13: mémoire cross-session — 3 derniers échanges + préférences
    memory_ctx = ""
    last_msgs = state.get("last_messages", [])
    if last_msgs:
        memory_ctx += "\nDerniers échanges:\n" + "\n".join(f"  - {m}" for m in last_msgs[-3:])
    prefs = state.get("preferences", {})
    if prefs:
        memory_ctx += "\nPréférences connues: " + ", ".join(f"{k}:{v}" for k, v in list(prefs.items())[:4])

    # Contexte émotionnel
    # AUDIT-FIX: ai_agent.py est un chemin de code distinct de structured_agent.py
    # (qui écrit customer.last_emotion ET state["last_emotion"] ensemble) — par
    # prudence, on retombe sur state si l'attribut customer n'est pas encore à jour.
    emotion = customer.last_emotion or state.get("last_emotion")
    emotion_hint = {
        "frustrated": "⚠ Client frustré — sois empathique, propose une solution rapide.",
        "urgent": "🚨 Client urgent — va directement à l'essentiel.",
        "hesitant": "Client hésitant — sois rassurant, mets en avant les garanties.",
    }.get(emotion or "", "")

    return f"""Tu es un agent commercial pour la boutique "{store.name}".
{lang_instruction}

RÈGLES:
1. Vendeur humain professionnel — jamais robotique.
2. Ne crée JAMAIS une commande sans confirmation EXPLICITE.
3. Ne mentionne jamais OpenAI, GPT ou l'IA.
4. Max 3 phrases. Prix TND 3 décimales.
5. État FSM: {state_label}
{emotion_hint}
{custom}
{memory_ctx}

CONTEXTE: {json.dumps(state, ensure_ascii=False)}"""


# ─── Intent detection ─────────────────────────────────────────────────────────
INTENT_PROMPT = """Détecte l'intention du message. Retourne UNIQUEMENT un JSON valide:
{
  "intent": "product_search | order_confirm | order_cancel | delivery_info | payment_inquiry | greeting | complaint | other",
  "product_query": "terme extrait ou null",
  "quantity": 1,
  "language": "fr | ar"
}"""

# ── ACTION 2 : Cache Redis réponses répétitives ────────────────────────────────
import hashlib as _hashlib

_CACHE_TTL = 3600
_CACHEABLE_INTENTS = {"greeting", "complaint", "other"}


async def _get_reply_cache(store_id: int, key: str) -> str | None:
    # HARDENING-FIX (post-sprint review): get_redis() is sync — never await it.
    # The previous `await get_redis()` raised TypeError silently swallowed by
    # the except, fully disabling the reply cache.
    try:
        from services.redis_lock import get_redis

        r = get_redis()
        return await r.get(f"reply_cache:{store_id}:{key}")
    except Exception as _exc:
        logger.warning("_get_reply_cache failed: %s", _exc)
        return None


async def _set_reply_cache(store_id: int, key: str, reply: str) -> None:
    try:
        from services.redis_lock import get_redis

        r = get_redis()  # HARDENING-FIX: sync factory, never await
        await r.setex(f"reply_cache:{store_id}:{key}", _CACHE_TTL, reply)
    except Exception as _exc:
        logger.warning("_set_reply_cache failed: %s", _exc)
        pass


def _cache_key_fn(text: str) -> str:
    # AUDIT FIX (Bandit B324): MD5 utilisé ici uniquement pour dériver une clé
    # de cache, pas pour de la sécurité. usedforsecurity=False lève le finding
    # sans changer le comportement (Python 3.9+).
    return _hashlib.md5(text[:100].encode(), usedforsecurity=False).hexdigest()


# ── ACTION 1 : Appel LLM unifié (intent + réponse en 1 call) ─────────────────
_UNIFIED_SYS = (
    'Tu es un agent commercial pour "{store_name}". {lang_instr}\n'
    "Vendeur humain professionnel, max 3 phrases. Ne mentionne jamais l'IA. Prix TND 3 décimales.\n"
    "FSM: {fsm}. {custom}\n\n"
    "Réponds UNIQUEMENT en JSON:\n"
    '{{"intent":"product_search|order_confirm|order_cancel|delivery_info|greeting|complaint|other",'
    '"product_query":null,"language":"fr",'
    '"reply":"Ta réponse directe si intents simple (greeting/complaint/other), sinon null"}}'
)


async def detect_intent_and_reply(
    message: str,
    store: "Store",
    customer: "Customer",
    tenant_id: int | None = None,
    channel: str = "whatsapp",
) -> tuple[dict, str | None]:
    """ACTION 1 — intent + réponse en 1 appel LLM. Gain latence 40-60%."""
    lang = customer.language or "fr"
    li = "Réponds en français." if lang == "fr" else "أجب باللغة العربية."
    # HIGH-12 FIX: valider profondeur/taille avant tout accès
    fsm = _sanitize_conversation_state(customer.conversation_state, getattr(customer, "id", None)).get(
        "fsm_state", "idle"
    )
    custom = getattr(store, "ai_agent_prompt", "") or ""
    system = _UNIFIED_SYS.format(store_name=store.name, lang_instr=li, fsm=fsm, custom=custom)
    try:
        r = await llm_chat(
            model=settings.OPENAI_LOW_COST_MODEL,
            max_tokens=300,
            temperature=0.7,
            tenant_id=tenant_id,
            agent_name="ai_agent.unified",
            channel=channel,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": message}],
        )
        raw = r.choices[0].message.content.strip().replace("```json", "").replace("```", "")
        data = json.loads(raw)
        intent = {
            "intent": data.get("intent", "other"),
            "product_query": data.get("product_query"),
            "quantity": data.get("quantity", 1),
            "language": data.get("language", "fr"),
        }
        return intent, data.get("reply")
    except Exception as e:
        logger.warning(f"Unified call failed: {e}")
        return {"intent": "other", "product_query": None, "quantity": 1, "language": "fr"}, None


async def detect_intent(message: str, tenant_id: int | None = None, channel: str = "whatsapp") -> dict:
    try:
        r = await llm_chat(
            model=settings.OPENAI_MODEL,
            max_tokens=150,
            tenant_id=tenant_id,
            agent_name="ai_agent.intent",
            channel=channel,
            messages=[
                {"role": "system", "content": INTENT_PROMPT},
                {"role": "user", "content": message},
            ],
        )
        raw = r.choices[0].message.content.strip().replace("```json", "").replace("```", "")
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Intent detection failed: {e}")
        return {"intent": "other", "product_query": None, "quantity": 1, "language": "fr"}


# ─── Delivery info extraction ─────────────────────────────────────────────────
DELIVERY_EXTRACT_PROMPT = """Extrais les infos de livraison du message.
Retourne UNIQUEMENT un JSON valide:
{
  "name": "nom complet ou null",
  "address": "adresse complète ou null",
  "payment_method": "flouci | clix | tnpay | cash | null",
  "complete": true/false,
  "missing": ["champs manquants"]
}
complete=true uniquement si name ET address sont présents."""


async def _extract_delivery_info(text: str, tenant_id: int | None = None, channel: str = "whatsapp") -> dict:
    try:
        r = await llm_chat(
            model=settings.OPENAI_MODEL,
            max_tokens=200,
            tenant_id=tenant_id,
            agent_name="ai_agent.delivery",
            channel=channel,
            messages=[
                {"role": "system", "content": DELIVERY_EXTRACT_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        raw = r.choices[0].message.content.strip().replace("```json", "").replace("```", "")
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Delivery extraction failed: {e}")
        return {"complete": False, "missing": ["nom", "adresse"]}


# ─── Product lookup ───────────────────────────────────────────────────────────
async def lookup_product_by_query(db: AsyncSession, store_id: int, query: str) -> list[dict]:
    stmt = (
        select(Product)
        .where(
            Product.store_id == store_id,
            Product.is_active,
            Product.stock_qty > 0,
            Product.name.ilike(f"%{query}%"),
        )
        .limit(5)
    )
    result = await db.execute(stmt)
    return [
        {"product_id": p.id, "name": p.name, "price": p.price, "stock": p.stock_qty, "image_url": p.image_url}
        for p in result.scalars().all()
    ]


# ─── Reply generator ──────────────────────────────────────────────────────────
async def generate_reply(
    system_prompt: str, context: str, tenant_id: int | None = None, channel: str = "whatsapp"
) -> str:
    r = await llm_chat(
        model=settings.OPENAI_MODEL,
        max_tokens=400,
        temperature=0.7,
        tenant_id=tenant_id,
        agent_name="ai_agent.reply",
        channel=channel,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ],
    )
    return r.choices[0].message.content.strip()


# ─── FSM: log transition ──────────────────────────────────────────────────────
async def _log_transition(
    db: AsyncSession,
    store_id: int,
    customer_id: int,
    from_state: str,
    to_state: str,
    trigger: str,
    payload: dict | None = None,
    order_id: int | None = None,
    channel: str = "whatsapp",
):
    log = ConversationLog(
        store_id=store_id,
        customer_id=customer_id,
        from_state=from_state,
        to_state=to_state,
        trigger=trigger,
        payload=payload,
        order_id=order_id,
        channel=channel,
    )
    db.add(log)
    # T8: track FSM transitions in Prometheus
    try:
        from services.metrics import fsm_transitions_total

        fsm_transitions_total.labels(
            store_id=str(store_id),
            from_state=from_state or "none",
            to_state=to_state,
        ).inc()
    except Exception as _exc:
        logger.warning("operation failed: %s", _exc)
        pass


# ─── Timeout check ────────────────────────────────────────────────────────────
def _check_timeout(customer: Customer, timeout_min: int) -> bool:
    """Returns True if conversation has timed out and state should be reset."""
    if not customer.last_message_at:
        return False
    now = datetime.now(UTC)
    last = customer.last_message_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    delta_min = (now - last).total_seconds() / 60
    return delta_min > timeout_min


# ─── Create Order ─────────────────────────────────────────────────────────────
async def _create_order_from_state(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    delivery: dict,
) -> Order | None:
    """
    M2 FIX: AI is a parsing tool, not a source of truth.
    All fields extracted by GPT are validated here before any DB mutation.
    """
    # HIGH-12 FIX: valider profondeur/taille avant création de commande
    state = _sanitize_conversation_state(customer.conversation_state, customer.id)
    last_product = state.get("last_product")
    if not last_product:
        logger.error("Cannot create order: no last_product in state")
        return None

    # ── M2: Business validation — never trust raw AI output directly ──────────
    errors = []

    name = delivery.get("name", "").strip()
    address = delivery.get("address", "").strip()

    if not name or len(name) < 2:
        errors.append("nom client invalide ou trop court")
    if not address or len(address) < 5:
        errors.append("adresse de livraison invalide ou trop courte")
    if len(name) > 200:
        errors.append("nom trop long")
    if len(address) > 500:
        errors.append("adresse trop longue")

    # Validate product exists and has valid price
    product_id = last_product.get("product_id")
    price = last_product.get("price", 0)
    if not product_id or not isinstance(price, int | float) or price <= 0:
        errors.append("produit invalide ou prix manquant")

    qty = state.get("quantity", 1)
    if not isinstance(qty, int) or qty < 1 or qty > 999:
        errors.append(f"quantité invalide: {qty}")

    if errors:
        logger.warning(f"Order validation failed for customer {customer.id}: {errors}")
        return None
    # ─────────────────────────────────────────────────────────────────────────

    try:
        items = [
            {
                "product_id": product_id,
                "name": last_product["name"],
                "qty": qty,
                "unit_price": price,
            }
        ]
        total = round(sum(i["qty"] * i["unit_price"] for i in items), 3)

        provider_map = {
            "flouci": "flouci",
            "clix": "clix",
            "clic": "clix",
            "tnpay": "tnpay",
            "cash": "cash",
            "espèce": "cash",
            "especes": "cash",
            "espèces": "cash",
        }
        raw_provider = (delivery.get("payment_method") or "cash").lower()
        provider = provider_map.get(raw_provider, "cash")

        # E19 FIX: atomic stock check + decrement under SELECT FOR UPDATE lock.
        # Prevents double-selling when multiple customers order the same product simultaneously.
        from sqlalchemy import select as sa_select

        product_result = await db.execute(
            sa_select(Product)
            .where(Product.id == product_id, Product.store_id == store.id)
            .with_for_update()  # row-level lock — other transactions block until this commits
        )
        product = product_result.scalar_one_or_none()

        if not product:
            logger.error(f"Product {product_id} not found in store {store.id} during order creation")
            return None

        available = product.stock_qty - product.stock_reserved
        if available < qty:
            logger.warning(
                f"Insufficient stock for product {product_id}: "
                f"available={available} (qty={product.stock_qty} reserved={product.stock_reserved}), requested={qty}"
            )
            return None  # caller will inform customer stock is insufficient

        # P1-FIX (audit): reserve stock, don't deduct it yet.
        # stock_qty must stay untouched at order-creation time — it is only
        # decremented on DELIVERED (api/v1/orders.py update_order_status).
        # Previously this line did `product.stock_qty -= qty` without ever
        # incrementing stock_reserved, which caused a double deduction on
        # DELIVERED and a permanent stock loss on CANCELLED/RETURNED (stock_qty
        # was never restored). Reserving here keeps `available = stock_qty -
        # stock_reserved` consistent across the whole order lifecycle.
        product.stock_reserved = (product.stock_reserved or 0) + qty
        db.add(product)

        order = Order(
            store_id=store.id,
            customer_id=customer.id,
            status=OrderStatus.CONFIRMED,
            items=items,
            total_amount=total,
            delivery_address=address,
            delivery_name=name,
            payment_provider=provider,
            notes="Commande créée via WhatsApp — agent IA",
        )
        db.add(order)
        await db.flush()
        logger.info(
            f"✅ Order #{order.id} created — store={store.id} "
            f"product={product_id} qty={qty} stock_remaining={product.stock_qty}"
        )
        # T8: track orders created per store + provider
        try:
            from services.metrics import orders_created_total

            orders_created_total.labels(
                store_id=str(store.id),
                payment_provider=provider,
            ).inc()
        except Exception as _exc:
            logger.warning("operation failed: %s", _exc)
            pass
        return order
    except Exception as e:
        logger.error(f"Order creation error: {e}")
        return None


# ─── Main: handle TEXT ────────────────────────────────────────────────────────
async def handle_text_message(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    text: str,
    wa_client,  # WhatsAppClient ou ChannelRouter (BLOC 10 — interface identique)
) -> str:
    # Déterminer le canal pour les logs FSM
    channel = getattr(wa_client, "channel", "whatsapp")
    # C5 FIX: re-fetch customer with FOR UPDATE lock to prevent concurrent FSM writes.
    # Two simultaneous messages from the same phone would otherwise both read the same
    # conversation_state and the second commit would overwrite the first silently.
    from sqlalchemy import select

    locked_result = await db.execute(select(Customer).where(Customer.id == customer.id).with_for_update())
    customer = locked_result.scalar_one_or_none() or customer

    timeout_min = getattr(store, "conversation_timeout_min", 30) or 30
    # HIGH-12 FIX: valider profondeur/taille avant toute manipulation FSM
    state = _sanitize_conversation_state(customer.conversation_state, customer.id)
    fsm = state.get("fsm_state", State.IDLE)

    # Auto-reset on timeout
    if _check_timeout(customer, timeout_min) and fsm not in (State.IDLE,):
        await _log_transition(db, store.id, customer.id, fsm, State.IDLE, "timeout", channel=channel)
        state = {}
        fsm = State.IDLE
        logger.info(f"Conversation timeout reset for customer {customer.whatsapp_phone}")

    # ACTION 1+2: appel unifié + cache Redis
    _ck = _cache_key_fn(text)
    _cached = await _get_reply_cache(store.id, _ck)
    if _cached and fsm == State.IDLE:
        customer.last_message_at = datetime.now(UTC)
        db.add(customer)
        return _cached
    intent, unified_reply = await detect_intent_and_reply(
        text, store=store, customer=customer, tenant_id=store.id, channel=channel
    )
    prev_fsm = fsm
    context = ""

    # ── FSM transitions ───────────────────────────────────────────────────────
    if intent["intent"] == "product_search" and intent.get("product_query"):
        products = await lookup_product_by_query(db, store.id, intent["product_query"])
        if products:
            p = products[0]
            alts = products[1:3]
            context = (
                f"Client cherche: '{text}'\n"
                f"Produit: {p['name']} — {p['price']:.3f} TND (stock: {p['stock']})\n"
                f"Alternatives: {alts}\n"
                f"Propose ce produit et demande s'il veut commander."
            )
            state.update({"last_product": p, "alternatives": alts, "fsm_state": State.PRODUCT_SHOWN})
            fsm = State.PRODUCT_SHOWN
        else:
            context = f"Client cherche: '{text}'\nAucun produit en stock. Présente des excuses et propose d'aider."
            state["fsm_state"] = State.BROWSING
            fsm = State.BROWSING

    elif intent["intent"] == "order_confirm" and state.get("last_product"):
        context = (
            f"Client confirme la commande: {state['last_product']['name']} — {state['last_product']['price']:.3f} TND\n"
            f"Demande: nom complet, adresse de livraison, mode de paiement (Flouci / Clic / TnPay / Cash)."
        )
        state["fsm_state"] = State.AWAITING_DELIVERY
        fsm = State.AWAITING_DELIVERY

    elif fsm == State.AWAITING_DELIVERY or intent["intent"] == "delivery_info":
        delivery = await _extract_delivery_info(text, tenant_id=store.id, channel=channel)
        if delivery.get("complete"):
            order = await _create_order_from_state(db, store, customer, delivery)
            if order:
                state.update({"fsm_state": State.ORDER_CREATED, "order_id": order.id})
                fsm = State.ORDER_CREATED
                await _log_transition(
                    db, store.id, customer.id, prev_fsm, fsm, "delivery_info", order_id=order.id, channel=channel
                )
                provider = order.payment_provider or "cash"
                if provider != "cash":
                    context = (
                        f"Commande #{order.id} créée! Total: {order.total_amount:.3f} TND\n"
                        f"Adresse: {order.delivery_address}\n"
                        f"Envoie le lien de paiement {provider.upper()} et confirme."
                    )
                else:
                    context = (
                        f"Commande #{order.id} confirmée! Total: {order.total_amount:.3f} TND\n"
                        f"Livraison à: {order.delivery_address}\n"
                        f"Paiement à la livraison. Remercie chaleureusement."
                    )
            else:
                # E19: could be stock insufficient or validation failure
                last_p = state.get("last_product", {})
                context = (
                    f"Impossible de créer la commande pour: {last_p.get('name', 'ce produit')}.\n"
                    f"Raison possible: stock insuffisant ou informations incomplètes.\n"
                    f"Informe le client poliment et propose des alternatives si disponibles."
                )
                # Keep state so customer can retry or choose alternative
                state["fsm_state"] = State.PRODUCT_SHOWN
        else:
            missing = delivery.get("missing", [])
            context = (
                f"Client répond: '{text}'\n"
                f"Infos manquantes: {', '.join(missing)}.\n"
                f"Demande poliment les infos manquantes."
            )

    elif intent["intent"] == "order_cancel":
        context = "Client annule. Remercie poliment et reste disponible."
        state = {"fsm_state": State.IDLE}
        fsm = State.IDLE

    elif intent["intent"] == "greeting" and fsm == State.IDLE:
        context = f"Client dit bonjour. Accueille-le chaleureusement et présente brièvement la boutique '{store.name}'."

    else:
        context = f"Message: '{text}'\nRéponds naturellement selon l'état de la conversation."

    system_prompt = build_system_prompt(store, customer)
    reply = unified_reply or await generate_reply(system_prompt, context or text, tenant_id=store.id, channel=channel)
    if intent["intent"] in _CACHEABLE_INTENTS and fsm == State.IDLE:
        await _set_reply_cache(store.id, _ck, reply)

    if fsm != prev_fsm:
        await _log_transition(db, store.id, customer.id, prev_fsm, fsm, f"text:{intent['intent']}", channel=channel)

    # Update customer
    customer.conversation_state = state
    customer.last_message_at = datetime.now(UTC)
    db.add(customer)
    await db.commit()

    await wa_client.send_text(customer.whatsapp_phone, reply)
    return reply


# ─── Main: handle IMAGE ───────────────────────────────────────────────────────
async def handle_image_message(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    media_id: str,
    wa_client: WhatsAppClient,
) -> dict:
    # C5 FIX: same lock as handle_text_message
    from sqlalchemy import select as sa_select

    locked = await db.execute(sa_select(Customer).where(Customer.id == customer.id).with_for_update())
    customer = locked.scalar_one_or_none() or customer

    vision = await analyze_whatsapp_image(media_id)
    logger.info(f"Vision: store={store.id} type={vision.get('type')} confidence={vision.get('confidence')}")

    match = await find_best_match(db, store.id, vision)
    state = customer.conversation_state or {}
    prev_fsm = state.get("fsm_state", State.IDLE)

    if match["found"] and match["match_score"] >= 0.5:
        context = (
            f"Client envoie une image.\n"
            f"Analyse IA: {vision.get('description_fr', vision.get('type', ''))}\n"
            f"Produit trouvé: {match['name']} — {match['price']:.3f} TND (stock: {match['stock']})\n"
            f"Score: {match['match_score']:.0%}\n"
            f"Informe le client et propose de commander avec des boutons."
        )
        state.update(
            {
                "last_product": match,
                "fsm_state": State.PRODUCT_SHOWN,
                "from_image": True,
            }
        )
        # Send product card with action buttons
        await wa_client.send_product_card(
            customer.whatsapp_phone,
            match["name"],
            match["price"],
            match["stock"],
        )
    elif match["found"]:
        alts = match.get("alternatives", [])
        context = (
            f"Client envoie une image: {vision.get('description_fr', '')}\n"
            f"Produit exact non trouvé. Alternatives: {alts[:2]}\n"
            f"Propose ces alternatives."
        )
        state["fsm_state"] = State.BROWSING
    else:
        context = (
            f"Client envoie une image: {vision.get('description_fr', 'produit non identifié')}\n"
            f"Aucun produit correspondant. Informe poliment."
        )

    system_prompt = build_system_prompt(store, customer)
    reply = await generate_reply(
        system_prompt,
        context,
        tenant_id=store.id,
        channel=getattr(wa_client, "channel", "whatsapp"),
    )

    new_fsm = state.get("fsm_state", State.IDLE)
    if new_fsm != prev_fsm:
        await _log_transition(
            db,
            store.id,
            customer.id,
            prev_fsm,
            new_fsm,
            "image",
            payload={"vision_type": vision.get("type"), "confidence": vision.get("confidence")},
        )

    customer.conversation_state = state
    customer.last_message_at = datetime.now(UTC)
    db.add(customer)
    await db.commit()

    # Only send text reply if we didn't send a product card
    if not (match["found"] and match["match_score"] >= 0.5):
        await wa_client.send_text(customer.whatsapp_phone, reply)

    return {"vision": vision, "match": match, "reply": reply}


# ─── Main: handle BUTTON ──────────────────────────────────────────────────────
async def handle_button_reply(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    button_id: str,
    button_title: str,
    wa_client: WhatsAppClient,
) -> str:
    state = customer.conversation_state or {}
    prev_fsm = state.get("fsm_state", State.IDLE)
    system_prompt = build_system_prompt(store, customer)
    channel = getattr(wa_client, "channel", "whatsapp")

    if button_id == "confirm_order":
        state["fsm_state"] = State.AWAITING_DELIVERY
        context = (
            f"Client clique Commander sur: {state.get('last_product', {}).get('name', 'le produit')}\n"
            f"Demande maintenant: nom complet, adresse, mode de paiement."
        )
    elif button_id == "see_alternatives":
        alts = state.get("alternatives", [])
        context = f"Client veut des alternatives. Disponibles: {alts}\nPrésente-les avec prix."
    elif button_id == "cancel":
        state = {"fsm_state": State.IDLE}
        context = "Client annule. Remercie chaleureusement et reste disponible."
    else:
        context = f"Client appuie sur: '{button_title}'. Réponds naturellement."

    reply = await generate_reply(system_prompt, context, tenant_id=store.id, channel=channel)

    new_fsm = state.get("fsm_state", State.IDLE)
    if new_fsm != prev_fsm:
        await _log_transition(db, store.id, customer.id, prev_fsm, new_fsm, f"button:{button_id}")

    customer.conversation_state = state
    customer.last_message_at = datetime.now(UTC)
    db.add(customer)
    await db.commit()

    await wa_client.send_text(customer.whatsapp_phone, reply)
    return reply


# ─── Post-payment WA notification ────────────────────────────────────────────
async def send_post_payment_notification(
    db: AsyncSession,
    order: Order,
    status: str,
):
    """
    P1-A5: Envoi automatique d'un message WA après confirmation de paiement.
    Appelé depuis reconcile_payment task.
    """
    from sqlalchemy import select as sa_select

    from models.database import Customer, Store

    store_result = await db.execute(sa_select(Store).where(Store.id == order.store_id))
    store = store_result.scalar_one_or_none()
    if not store:
        return

    customer_result = await db.execute(sa_select(Customer).where(Customer.id == order.customer_id))
    customer = customer_result.scalar_one_or_none()
    if not customer:
        return

    wa_client = WhatsAppClient(store)

    if status in ("paid", "SUCCESS", "COMPLETED", "success"):
        # Custom message or default
        msg = store.post_payment_msg or (
            f"✅ Paiement confirmé!\n"
            f"Commande #{order.id} — {order.total_amount:.3f} TND\n"
            f"Livraison en cours. Merci pour votre confiance!"
        )
        # Reset conversation state
        if customer.conversation_state:
            customer.conversation_state = {"fsm_state": State.IDLE}
            db.add(customer)
    elif status in ("failed", "FAILED", "cancelled", "CANCELLED"):
        msg = (
            f"❌ Paiement échoué pour la commande #{order.id}.\n"
            f"Voulez-vous réessayer ou choisir un autre mode de paiement?"
        )
    else:
        return

    try:
        await wa_client.send_text(customer.whatsapp_phone, msg)
        logger.info(f"Post-payment WA sent to {customer.whatsapp_phone} — order #{order.id} status={status}")
    except Exception as e:
        logger.error(f"Post-payment WA send failed: {e}")


async def send_whatsapp_text(*, store_id: int, phone: str, text: str, db: AsyncSession) -> dict:
    """Envoie un message sortant pour une tâche Celery isolée.

    Le wrapper tasks fournit uniquement le store_id et la session dédiée ; cette
    façade résout donc le Store avant d'utiliser le même client WhatsApp que les
    autres chemins de l'agent. Un Store absent est retourné explicitement comme
    erreur métier, plutôt que de provoquer un import ou un envoi implicite.
    """
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        return {"sent": False, "reason": "store_not_found"}
    client = WhatsAppClient(store)
    await client.send_text(phone, text)
    return {"sent": True, "phone": phone, "store_id": store_id}


async def handle_whatsapp_message(*, store_id: int, customer_phone: str, message_text: str, db: AsyncSession) -> dict:
    """Façade worker pour le traitement WhatsApp entrant."""
    store_result = await db.execute(select(Store).where(Store.id == store_id))
    store = store_result.scalar_one_or_none()
    if not store:
        return {"status": "error", "reason": "store_not_found"}
    customer_result = await db.execute(
        select(Customer).where(Customer.store_id == store_id, Customer.whatsapp_phone == customer_phone)
    )
    customer = customer_result.scalar_one_or_none()
    if not customer:
        return {"status": "error", "reason": "customer_not_found"}
    reply = await handle_text_message(db=db, store=store, customer=customer, text=message_text, wa_client=WhatsAppClient(store))
    return {"status": "ok", "reply": reply}
