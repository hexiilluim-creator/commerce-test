
# B1-FIX: All LLM calls route through llm_gateway.chat() — never call OpenAI directly.
# This ensures quota tracking, budget enforcement, circuit breaker and BYOK
# all apply uniformly whether this is structured_agent or ai_agent.
# get_platform_client() is intentionally NOT imported here.


"""
structured_agent.py — Agent IA WhatsApp structuré avec Pipeline Intention/Émotion
=============================================================================
Ce module implémente une approche hybride :
1. Détection d'intention et d'émotion via LLM.
2. Machine à états (FSM) pour le routage métier.
3. Handlers spécifiques pour chaque état.
4. Persistance des émotions et préférences client.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import (
    Customer,
    Order,
    OrderStatus,
    Product,
    Store,
)
from services.ai_agent import _check_timeout, _log_transition
from services.conversation_state import ConversationState
from services.embedding_search import search_products as existing_search_products
from utils.llm_parser import parse_llm_json
from utils.whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)

# ─── Constantes d'États ───────────────────────────────────────────────────────
MAIN_MENU = "main_menu"
BROWSING = "browsing"
ORDER_CONFIRMATION = "order_confirmation"
IDLE = "idle"

# ─── Émotions autorisées ──────────────────────────────────────────────────────
ALLOWED_EMOTIONS = ["interested", "hesitant", "frustrated", "urgent"]

# ─── Prompts ──────────────────────────────────────────────────────────────────
INTENT_EMOTION_PROMPT = f"""Analyse le message du client pour une boutique e-commerce. 
Le client peut s'exprimer en Français, Arabe classique ou en Darija Tunisienne (ex: 'nheb nechri', 'famma t-shirt k'hal?', 'fin woslet l'commande?').

Retourne UNIQUEMENT un JSON valide :
{{
  "intent": "product_search | order_status | talk_to_human | greeting | order_confirm | cancel | other",
  "emotion": "interested | hesitant | frustrated | urgent",
  "product_query": "terme de recherche ou null",
  "preferences": ["sport", "pas cher", etc] ou [],
  "detected_language": "fr | ar | darija"
}}

Règles :
- intent: 'product_search' si cherche un produit, 'order_status' si suit commande, 'talk_to_human' si veut un conseiller.
- emotion: Choisis parmi {ALLOWED_EMOTIONS}. Par défaut 'interested'.
- detected_language: Identifie la langue utilisée.
"""

# ─── 2️⃣ INTENT + EMOTION ──────────────────────────────────────────────────────

async def detect_intent_and_emotion(message: str) -> dict:
    """Détecte l'intention, l'émotion et les préférences du client.

    B1-FIX: Appel routé via llm_gateway.chat() pour bénéficier des quotas
    tenant, du budget $/mois, du circuit breaker et du BYOK — exactement
    comme ai_agent.py. N'appelle JAMAIS get_platform_client() directement.
    """
    try:
        from services import llm_gateway  # import local pour éviter import circulaire
        r = await llm_gateway.chat(
            messages=[
                {"role": "system", "content": INTENT_EMOTION_PROMPT},
                {"role": "user", "content": message},
            ],
            agent_name="structured_agent.intent",
            max_tokens=150,
        )
        data = parse_llm_json(r.choices[0].message.content, caller="structured_agent")
        
        # Validation émotion
        if data.get("emotion") not in ALLOWED_EMOTIONS:
            data["emotion"] = "interested"
            
        return data
    except Exception as e:
        logger.warning(f"Intent/Emotion detection failed: {e}")
        return {
            "intent": "other", 
            "emotion": "interested", 
            "product_query": None, 
            "preferences": []
        }

# ─── 4️⃣ MENU WHATSAPP ─────────────────────────────────────────────────────────

def send_main_menu(lang: str = "fr") -> str:
    """Retourne le texte du menu principal en fonction de la langue."""
    if lang == "darija":
        return (
            "👋 *Asslema bikom!*\n\n"
            "Chnouwa najem n'aawnek lyoum?\n"
            "1️⃣ *Chouf l'produitét mteena*\n"
            "2️⃣ *Tabba3 l'commande mteek*\n"
            "3️⃣ *Ahki maa conseiller*\n\n"
            "Ekhtar ra9m mel les choix elli louta."
        )
    return (
        "👋 *Bienvenue chez nous !*\n\n"
        "Comment puis-je vous aider aujourd'hui ?\n"
        "1️⃣ *Voir nos produits*\n"
        "2️⃣ *Suivre ma commande*\n"
        "3️⃣ *Parler à un conseiller*\n\n"
        "Tapez simplement le numéro de votre choix."
    )

# ─── VERROUILLAGE CONVERSATION CLIENT ─────────────────────────────────────────

_REDIS_LOCK_WAIT_SECONDS = 5.0
_REDIS_LOCK_POLL_SECONDS = 0.05
_REDIS_LOCK_TTL_SECONDS = 30


def _customer_lock_key(customer_id: int) -> str:
    return f"structured_agent:customer:{customer_id}"


@asynccontextmanager
async def _customer_processing_lock(customer_id: int):
    """Sérialise le traitement par customer_id.

    Ordre de protection :
    1. lock Redis best-effort pour sérialiser cross-worker
    2. SELECT ... FOR UPDATE plus bas pour l'intégrité transactionnelle DB
    """
    acquired = False
    try:
        from services.redis_lock import lock_service

        deadline = monotonic() + _REDIS_LOCK_WAIT_SECONDS
        while monotonic() < deadline:
            try:
                acquired = await lock_service.try_acquire(
                    _customer_lock_key(customer_id),
                    timeout=_REDIS_LOCK_TTL_SECONDS,
                )
            except Exception as exc:  # pragma: no cover - fallback runtime
                logger.warning("customer lock unavailable for customer=%s: %s", customer_id, exc)
                break
            if acquired:
                break
            await asyncio.sleep(_REDIS_LOCK_POLL_SECONDS)

        if not acquired:
            logger.warning(
                "customer lock busy for customer=%s — fallback to DB row lock only",
                customer_id,
            )

        yield
    finally:
        if acquired:
            try:
                from services.redis_lock import lock_service

                await lock_service.release(_customer_lock_key(customer_id))
            except Exception as exc:  # pragma: no cover - fallback runtime
                logger.warning("customer lock release failed for customer=%s: %s", customer_id, exc)


async def _load_customer_for_update(db: AsyncSession, customer: Customer) -> Customer:
    locked_result = await db.execute(
        select(Customer).where(Customer.id == customer.id).with_for_update()
    )
    return locked_result.scalar_one_or_none() or customer

# ─── 1️⃣ CORE HANDLER ──────────────────────────────────────────────────────────

async def handle_message(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    message: str,
    wa_client: WhatsAppClient
) -> str:
    """Point d'entrée principal pour le traitement des messages (Pipeline)."""

    async with _customer_processing_lock(customer.id):
        # L'appel LLM peut être coûteux : on le fait hors verrou DB, mais sous
        # verrou Redis best-effort pour sérialiser le traitement cross-worker.
        analysis = await detect_intent_and_emotion(message)

        # Verrou transactionnel DB : garantit qu'un seul commit FSM modifie la
        # ligne customer à la fois, même si Redis est indisponible.
        customer = await _load_customer_for_update(db, customer)

        state = ConversationState.from_customer(customer)
        current_fsm = state.get("fsm_state", IDLE)

        # Reset sur timeout
        timeout_min = getattr(store, "conversation_timeout_min", 30) or 30
        if _check_timeout(customer, timeout_min) and current_fsm != IDLE:
            await _log_transition(db, store.id, customer.id, current_fsm, IDLE, "timeout")
            state.clear()
            current_fsm = IDLE

        intent = analysis.get("intent")
        emotion = analysis.get("emotion")

        # Mise à jour de la mémoire client (9️⃣)
        prefs = customer.preferences or {}
        for p in analysis.get("preferences", []):
            prefs[p] = prefs.get(p, 0) + 1

        customer.preferences = prefs
        customer.last_emotion = emotion
        state["last_emotion"] = emotion  # compat rétro avec handlers

        # ACTION 4: Alerte proactive Slack si frustration/urgence
        if emotion in ("frustrated", "urgent"):
            try:
                import asyncio as _aio

                from services.emotion_alerts import trigger_emotion_alert_if_needed
                _ch = getattr(wa_client, "channel", "whatsapp")
                _aio.ensure_future(trigger_emotion_alert_if_needed(
                    store_id=store.id, store_name=store.name, customer_id=customer.id,
                    customer_phone=customer.whatsapp_phone or str(customer.id),
                    channel=_ch, emotion=emotion, message_preview=message[:300],
                ))
            except Exception as _ea:
                logger.debug("emotion_alert skip: %s", _ea)
        elif emotion == "interested":
            try:
                import asyncio as _aio

                from services.emotion_alerts import reset_frustration_counter
                _aio.ensure_future(reset_frustration_counter(store.id, customer.id))
            except Exception as _exc:
                logger.warning("operation failed: %s", _exc)
                pass

        # Détection de la langue pour la réponse
        lang = analysis.get("detected_language", "fr")
        state["last_lang"] = lang

        # Premier message ou retour au menu
        if current_fsm == IDLE or intent == "greeting":
            reply = send_main_menu(lang)
            state["fsm_state"] = MAIN_MENU
            await _log_transition(db, store.id, customer.id, current_fsm, MAIN_MENU, "greeting")
        else:
            # Le même wrapper state est propagé à tous les handlers : aucune
            # dépendance à un write-back manuel n'est nécessaire.
            reply = await route(db, store, customer, analysis, message, wa_client, state=state)

        # Préserver emotion + langue au-dessus des mutations métier.
        state["last_emotion"] = emotion
        state["last_lang"] = lang
        state.sync()

        customer.last_message_at = datetime.now(UTC)
        db.add(customer)
        await db.commit()

    # Envoi de la réponse hors transaction DB
    await wa_client.send_text(customer.whatsapp_phone, reply)
    return reply

# ─── 3️⃣ STATE MACHINE SIMPLE ──────────────────────────────────────────────────

async def route(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    analysis: dict,
    message: str,
    wa_client: WhatsAppClient,
    state: ConversationState | None = None,
) -> str:
    """Routeur basé sur l'état de la session."""
    state = state or ConversationState.from_customer(customer)
    fsm = state.get("fsm_state", MAIN_MENU)

    try:
        if fsm == MAIN_MENU:
            return await handle_main_menu(db, store, customer, analysis, message, state=state)
        elif fsm == BROWSING:
            return await handle_browsing(db, store, customer, analysis, message, state=state)
        elif fsm == ORDER_CONFIRMATION:
            return await handle_order_confirmation(db, store, customer, analysis, message, state=state)
        else:
            return send_main_menu()
    except Exception as e:
        logger.error(f"Routing error: {e}")
        return "Désolé, j'ai rencontré une petite erreur. Comment puis-je vous aider ? (Tapez 0 pour le menu)"

# ─── 6️⃣ RECHERCHE ──────────────────────────────────────────────────────────────

async def search_products(db: AsyncSession, store_id: int, query: str) -> list[Product]:
    """Recherche de produits compatible avec l'existant."""
    try:
        results = await existing_search_products(db, store_id, {"keywords": [query]})
        if results:
            product_ids = [r["product_id"] for r in results[:3]]
            stmt = select(Product).where(Product.id.in_(product_ids))
            res = await db.execute(stmt)
            return list(res.scalars().all())
    except Exception as e:
        logger.warning(f"Advanced search failed, falling back to SQL: {e}")
    
    stmt = select(Product).where(
        Product.store_id == store_id,
        Product.is_active,
        Product.stock_qty > 0,
        Product.name.ilike(f"%{query}%")
    ).limit(3)
    res = await db.execute(stmt)
    return list(res.scalars().all())

# ─── 5️⃣ PRODUITS + FORMAT ─────────────────────────────────────────────────────

def format_product(product: Product) -> str:
    """Formate un produit pour WhatsApp (interface publique — M2 FIX: delegates to localized version)."""
    return format_product_localized(product, lang="fr")

# ─── HANDLERS DE NAVIGATION ──────────────────────────────────────────────────

async def handle_main_menu(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    analysis: dict,
    message: str,
    state: ConversationState | None = None,
) -> str:
    """Gère les choix du menu principal."""
    state = state or ConversationState.from_customer(customer)
    lang = state.get("last_lang", "fr")

    if "1" in message or "produit" in message.lower() or analysis["intent"] == "product_search":
        state["fsm_state"] = BROWSING
        if lang == "darija":
            return "Chnouwa t'lawej lyoum? (ex: 't-shirt k'hal', 'sabbat sport')"
        return "Que recherchez-vous aujourd'hui ? (ex: 't-shirt noir', 'chaussures de sport')"

    elif "2" in message or "commande" in message.lower() or analysis["intent"] == "order_status":
        # No state change — stay in MAIN_MENU waiting for order number
        if lang == "darija":
            return "Bech ntabba3 l'commande mteek, aatini ra9m l'commande wala esmek l'kemel."
        return "Pour suivre votre commande, merci de me donner votre numéro de commande ou votre nom complet."

    elif "3" in message or "conseiller" in message.lower() or analysis["intent"] == "talk_to_human":
        if lang == "darija":
            return "Conseiller bech ykallemek aala WhatsApp f'a9rab wa9t. Nab9a maak ken t'heb tes'el haja okhra!"
        return "Un conseiller va vous contacter sur ce numéro WhatsApp sous peu. En attendant, je reste à votre disposition !"

    else:
        if lang == "darija":
            return "Ma f'hemtkech bel gda. Ekhtar *1*, *2* wala *3*.\n\n" + send_main_menu(lang)
        return "Je n'ai pas bien compris. Veuillez répondre par *1*, *2* ou *3*.\n\n" + send_main_menu(lang)

async def handle_browsing(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    analysis: dict,
    message: str,
    state: ConversationState | None = None,
) -> str:
    """Gère la navigation et la recherche de produits."""
    state = state or ConversationState.from_customer(customer)
    lang = state.get("last_lang", "fr")

    if message.strip() == "0":
        state["fsm_state"] = MAIN_MENU
        return send_main_menu(lang)

    if message.strip() == "1" and state.get("selected_product_id"):
        # M1 FIX: set ORDER_CONFIRMATION BEFORE calling the sub-handler,
        # so the state is consistent if anything fails mid-handler.
        state["fsm_state"] = ORDER_CONFIRMATION
        return await handle_order_confirmation(db, store, customer, analysis, "INIT", state=state)

    if message.strip() == "2":
        # "Voir un autre produit" — clear selected and ask again
        state.pop("selected_product_id", None)
        if lang == "darija":
            return "D'accord ! Chnouwa t'heb tchouf ekher ?"
        return "D'accord ! Que cherchez-vous d'autre ?"

    query = analysis.get("product_query") or message

    # M3 FIX: enrich query with top customer preferences (most frequent first)
    # so the search reflects what this customer tends to buy.
    if customer.preferences:
        top_prefs = sorted(customer.preferences.items(), key=lambda x: x[1], reverse=True)
        pref_terms = [p for p, _ in top_prefs[:2]]  # top 2 preferences
        if pref_terms:
            enriched = f"{query} {' '.join(pref_terms)}"
            logger.debug(f"Query enriched with preferences: '{query}' -> '{enriched}'")
            query = enriched

    products = await search_products(db, store.id, query)

    if not products:
        if customer.last_emotion == "frustrated":
            if lang == "darija":
                return "Samahni mal9itech elli t'lawej aalih. Najem n'aawnek b'haja okhra? Chnouwa t'heb bedhabt?"
            return "Je suis vraiment désolé de ne pas trouver ce que vous cherchez. Pouvez-vous essayer avec un autre mot-clé ? Je vais faire de mon mieux !"

        if lang == "darija":
            return "Désolé, mal9itech produitét hakka. Jarreb kelma okhra (ex: 'chemise', 'nike')!"
        return "Désolé, je n'ai pas trouvé de produits correspondant à votre recherche. Essayez un autre mot-clé (ex: 'chemise', 'nike') !"

    product = products[0]
    state["selected_product_id"] = product.id

    prefix = ""
    if customer.last_emotion == "urgent":
        if lang == "darija":
            prefix = "🚀 *Fisa3 fisa3!* Chouf chnouwa 9aad lina fel stock:\n\n"
        else:
            prefix = "🚀 *On fait vite !* Voici ce qu'il nous reste en stock :\n\n"

    return prefix + format_product_localized(product, lang)

def format_product_localized(product: Product, lang: str = "fr") -> str:
    """Formate un produit avec les labels traduits."""
    desc = product.description[:100] + "..." if product.description and len(product.description) > 100 else (product.description or "")
    
    if lang == "darija":
        return (
            f"🔥 *{product.name}*\n"
            f"💰 *Soum : {product.price:.3f} TND*\n"
            f"📦 Stock : {product.stock_qty} disponible(s)\n"
            f"📝 {desc}\n\n"
            f"👉 Tapez *1* bech techri\n"
            f"👉 Tapez *2* bech tchouf haja okhra\n"
            f"👉 Tapez *0* bech tarjaa lel menu"
        )
    
    return (
        f"🔥 *{product.name}*\n"
        f"💰 *Prix : {product.price:.3f} TND*\n"
        f"📦 Stock : {product.stock_qty} disponible(s)\n"
        f"📝 {desc}\n\n"
        f"👉 Tapez *1* pour l'acheter\n"
        f"👉 Tapez *2* pour voir un autre produit\n"
        f"👉 Tapez *0* pour revenir au menu"
    )

# ─── 7️⃣ COMMANDE SÉCURISÉE ────────────────────────────────────────────────────

async def create_order_safe(db: AsyncSession, store: Store, customer: Customer, product_id: int) -> Order | None:
    """Crée une commande de manière sécurisée avec vérification de stock."""
    try:
        stmt = select(Product).where(Product.id == product_id, Product.store_id == store.id).with_for_update()
        res = await db.execute(stmt)
        product = res.scalar_one_or_none()
        
        if not product or product.stock_qty <= 0:
            return None
            
        order = Order(
            store_id=store.id,
            customer_id=customer.id,
            status=OrderStatus.PENDING,
            items=[{
                "product_id": product.id,
                "name": product.name,
                "qty": 1,
                "unit_price": product.price
            }],
            total_amount=product.price,
            notes="Commande via Structured Agent"
        )
        
        product.stock_qty -= 1
        db.add(order)
        db.add(product)
        await db.flush()
        return order
    except Exception as e:
        logger.error(f"Safe order creation failed: {e}")
        return None

async def handle_order_confirmation(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    analysis: dict,
    message: str,
    state: ConversationState | None = None,
) -> str:
    """Gère le tunnel de commande avec génération automatique de lien de paiement."""
    state = state or ConversationState.from_customer(customer)
    lang = state.get("last_lang", "fr")
    product_id = state.get("selected_product_id")

    if not product_id:
        state["fsm_state"] = MAIN_MENU
        if lang == "darija":
            return "Samahni, mal9itech l'produit mteek. Arjaa lel menu.\n\n" + send_main_menu(lang)
        return "Désolé, je ne retrouve pas votre produit. Retour au menu.\n\n" + send_main_menu(lang)

    stmt = select(Product).where(Product.id == product_id)
    res = await db.execute(stmt)
    product = res.scalar_one_or_none()

    if not product:
        state["fsm_state"] = BROWSING
        if lang == "darija":
            return "L'produit hedha wfa. Chnouwa t'heb tchouf ekher?"
        return "Ce produit n'est plus disponible. Que cherchez-vous d'autre ?"

    if message == "INIT":
        # State stays ORDER_CONFIRMATION — already set by handle_browsing
        if lang == "darija":
            return (
                f"📝 *Résumé mte3 l'commande*\n\n"
                f"Produit : *{product.name}*\n"
                f"Soum : *{product.price:.3f} TND*\n\n"
                f"T'heb t'confirmé l'be3a?\n"
                f"✅ Tapez *Oui* bech t'confirmé\n"
                f"❌ Tapez *Non* bech t'annulé"
            )
        return (
            f"📝 *Résumé de votre commande*\n\n"
            f"Produit : *{product.name}*\n"
            f"Total : *{product.price:.3f} TND*\n\n"
            f"Confirmez-vous l'achat ?\n"
            f"✅ Tapez *Oui* pour confirmer\n"
            f"❌ Tapez *Non* pour annuler"
        )

    if "oui" in message.lower() or "✅" in message:
        order = await create_order_safe(db, store, customer, product_id)
        if order:
            state["fsm_state"] = IDLE
            state["last_order_id"] = order.id
            state.pop("selected_product_id", None)

            # ── Génération automatique du lien de paiement ────────────────────
            # Si le store a un provider de paiement configuré, générer et envoyer
            # le lien directement sur le canal d'origine.
            payment_suffix = ""
            if store.payment_config and store.onboarding_completed:
                try:
                    from services.payment_link_ai_tool import generate_payment_link_for_ai
                    # Récupérer le channel_client depuis le contexte (wa_client passé en paramètre)
                    # Note: wa_client n'est pas disponible ici, le lien sera créé sans envoi direct
                    pl_result = await generate_payment_link_for_ai(
                        db=db,
                        store=store,
                        customer=customer,
                        amount=order.total_amount,
                        description=f"Commande #{order.id} — {order.items[0]['name'] if order.items else 'Produit'}",
                        order_id=order.id,
                        channel=state.get("channel", "whatsapp"),
                        channel_client=None,  # Envoi géré par le retour de texte
                    )
                    if pl_result.get("success") and pl_result.get("url"):
                        payment_suffix = (
                            f"\n\n💳 *Lien de paiement :*\n{pl_result['url']}\n"
                            f"📋 Réf. facture : {pl_result.get('invoice_number', '')}"
                        )
                except Exception as _pe:
                    logger.warning("Génération lien de paiement post-commande échouée : %s", _pe)
            # ─────────────────────────────────────────────────────────────────

            if lang == "darija":
                return (
                    f"✅ *Commande #{order.id} t'9aydet!*\n\n"
                    f"Yaatik saha {customer.name or ''}! Taw n'kallmouk f'a9rab wa9t bech n'thabtou l'livraison."
                    f"{payment_suffix}"
                )
            return (
                f"✅ *Commande #{order.id} enregistrée !*\n\n"
                f"Merci {customer.name or ''} ! Nous allons vous contacter très prochainement pour valider la livraison."
                f"{payment_suffix}"
            )
        else:
            state["fsm_state"] = BROWSING
            state.pop("selected_product_id", None)
            if lang == "darija":
                return "Samahni, l'produit wfa tawwa bedhabt. T'heb tchouf haja okhra?"
            return "Désolé, le produit vient de tomber en rupture de stock à l'instant. Souhaitez-vous voir autre chose ?"

    elif "non" in message.lower() or "❌" in message or "0" in message:
        state["fsm_state"] = BROWSING
        if lang == "darija":
            return "Mouch mochkel! Nab9a maak, chnouwa t'heb tchouf ekher?"
        return "Pas de souci ! Je reste à votre disposition. Que souhaitez-vous voir d'autre ?"

    else:
        if lang == "darija":
            return "Amel mziya, confirmili b *Oui* wala *Non*."
        return "Veuillez confirmer par *Oui* ou *Non*."

# ─── 8️⃣ RELANCE CELERY ────────────────────────────────────────────────────────

from services.celery_app import celery_app


@celery_app.task(name="services.structured_agent.relance_users")
def relance_users():
    """Tâche Celery pour relancer les utilisateurs inactifs (toutes les 15 min)."""

    from sqlalchemy import select

    from models.database import AsyncSessionLocal, Customer, Store
    from utils.whatsapp_client import WhatsAppClient

    async def _run():
        async with AsyncSessionLocal() as db:
            now = datetime.now(UTC)

            # 1K-TENANT FIX: store-partitioned batching for fairness across 1000 tenants.
            # Fetch at most _MAX_STORES_PER_RUN distinct active stores per Beat tick,
            # then process at most _MAX_PER_STORE customers per store.
            # Prevents one large tenant from consuming the entire relance budget.
            _MAX_STORES_PER_RUN = 50
            _MAX_PER_STORE = 10

            from sqlalchemy import distinct as _distinct
            store_ids_res = await db.execute(
                select(_distinct(Customer.store_id))
                .where(
                    Customer.last_message_at.isnot(None),
                    Customer.conversation_state.isnot(None),
                )
                .limit(_MAX_STORES_PER_RUN)
            )
            active_store_ids = [row[0] for row in store_ids_res.fetchall()]

            sent_count = 0

            for sid in active_store_ids:
                batch_res = await db.execute(
                    select(Customer)
                    .where(
                        Customer.store_id == sid,
                        Customer.last_message_at.isnot(None),
                        Customer.conversation_state.isnot(None),
                    )
                    .limit(_MAX_PER_STORE)
                )
                customers = batch_res.scalars().all()

                for customer in customers:
                    state = ConversationState.from_customer(customer)
                    fsm = state.get("fsm_state", IDLE)

                    if fsm == IDLE:
                        continue

                    # Skip if already relanced within 2h window
                    if state.get("relanced_at"):
                        try:
                            from datetime import datetime as _dt
                            relanced_at = _dt.fromisoformat(state["relanced_at"])
                            if relanced_at.tzinfo is None:
                                relanced_at = relanced_at.replace(tzinfo=UTC)
                            if (now - relanced_at).total_seconds() < 7200:
                                continue
                        except (ValueError, TypeError):
                            pass

                    last_msg = customer.last_message_at
                    if last_msg.tzinfo is None:
                        last_msg = last_msg.replace(tzinfo=UTC)
                    diff_min = (now - last_msg).total_seconds() / 60
                    if not (30 <= diff_min <= 60):
                        continue

                    from services.tenant_access import is_tenant_active
                    if not await is_tenant_active(db, int(customer.store_id)):
                        logger.info("relance_users: skipped suspended tenant store_id=%s", customer.store_id)
                        continue

                    store_res = await db.execute(
                        select(Store).where(Store.id == customer.store_id, Store.is_active)
                    )
                    store = store_res.scalar_one_or_none()
                    if not store:
                        continue

                    wa = WhatsAppClient(store)
                    emotion = customer.last_emotion or "interested"

                    if emotion == "hesitant":
                        msg = "Besoin d'un petit coup de pouce pour choisir ? Je suis là pour répondre à vos questions ! 😊"
                    elif emotion == "frustrated":
                        msg = "Je reviens vers vous pour m'assurer que vous avez trouvé votre bonheur. Puis-je vous aider ? 🙏"
                    elif emotion == "urgent":
                        msg = "🚀 Je vois que vous étiez pressé(e) ! Ce produit est toujours disponible. Souhaitez-vous finaliser ?"
                    else:
                        msg = "Toujours intéressé(e) par nos produits ? N'hésitez pas, je suis à votre écoute ! ✨"

                    try:
                        await wa.send_text(customer.whatsapp_phone, msg)
                        state["relanced_at"] = now.isoformat()
                        state.sync()
                        db.add(customer)
                        sent_count += 1
                    except Exception as e:
                        logger.warning("Relance send failed for %s: %s", customer.whatsapp_phone, e)

            await db.commit()
            logger.info("relance_users: %d messages sent across %d stores", sent_count, len(active_store_ids))

    from services.tasks import run_async
    run_async(_run())


async def run_agent(*, store_id: int, context: dict, db: AsyncSession) -> dict:
    """Façade pour les tâches internes qui déclenchent l’agent structuré.

    Le contexte doit fournir ``customer_id`` et ``message``. Les cas incomplets
    sont retournés explicitement afin que les workers ne masquent pas une
    mauvaise file de travail derrière une exception d’import.
    """
    customer_id = context.get("customer_id") if isinstance(context, dict) else None
    message = context.get("message") if isinstance(context, dict) else None
    if not customer_id or not message:
        return {"success": False, "reason": "customer_id_and_message_required"}
    store_result = await db.execute(select(Store).where(Store.id == store_id))
    store = store_result.scalar_one_or_none()
    if not store:
        return {"success": False, "reason": "store_not_found"}
    customer_result = await db.execute(select(Customer).where(Customer.id == customer_id, Customer.store_id == store_id))
    customer = customer_result.scalar_one_or_none()
    if not customer:
        return {"success": False, "reason": "customer_not_found"}
    reply = await handle_message(db, store, customer, message, WhatsAppClient(store))
    return {"success": True, "reply": reply, "customer_id": customer_id}
