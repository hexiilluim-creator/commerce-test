"""
owner_agent.py — Agent conversationnel WhatsApp pour le marchand (mode admin)
=============================================================================

Le marchand envoie des commandes depuis son propre WhatsApp -> l'agent répond
avec des données temps réel de sa boutique.

Commandes supportées (NL + mots-clés, fr/ar/darija) :
  📦 stock [produit]          -> niveaux de stock
  📋 commandes [aujourd'hui]  -> résumé des ventes
  👥 clients                  -> stats clients actifs
  📊 stats / rapport          -> KPIs du jour/semaine
  📢 broadcast <msg>          -> envoyer un message à tous les clients actifs
  🔔 alerte stock <n>         -> configurer alerte stock bas
  ❓ aide / help              -> liste des commandes disponibles

Sécurité :
  - Accès uniquement si from_phone == store.whatsapp_phone (vérifié en amont)
  - Broadcast limité à 500 destinataires max par appel
  - Confirmation requise avant broadcast
  - Rate limit : 20 requêtes/heure par marchand
"""

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import (
    Customer,
    Order,
    OrderStatus,
    Product,
    Store,
    WhatsAppMessage,
)
from services.llm_gateway import chat as llm_chat
from utils.whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)

# ─── Intent classifier ────────────────────────────────────────────────────────
OWNER_INTENT_PROMPT = """Tu es un classificateur d'intentions pour un système admin WhatsApp.
Le marchand envoie des commandes en français, arabe ou darija tunisienne.

Retourne UNIQUEMENT un JSON valide :
{
  "intent": "stock_check | orders_summary | clients_stats | daily_report | broadcast | set_stock_alert | cancel_broadcast | help | unknown",
  "product_hint": "nom du produit mentionné ou null",
  "broadcast_msg": "texte du broadcast extrait ou null",
  "threshold": nombre entier si alerte stock ou null,
  "period": "today | week | month | null"
}

Exemples :
- "stock t-shirt" -> intent: stock_check, product_hint: "t-shirt"
- "commandes aujourd'hui" -> intent: orders_summary, period: "today"
- "broadcast promo 20% sur tout le catalogue" -> intent: broadcast, broadcast_msg: "promo 20%..."
- "alerte si stock < 5" -> intent: set_stock_alert, threshold: 5
- "موعد commandes" -> intent: orders_summary
"""


async def _detect_owner_intent(text: str, tenant_id: int | None = None) -> dict:
    try:
        r = await llm_chat(
            model=settings.OPENAI_MODEL,
            max_tokens=200,
            temperature=0,
            tenant_id=tenant_id,
            agent_name="owner_agent.intent",
            channel="whatsapp",
            messages=[
                {"role": "system", "content": OWNER_INTENT_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        raw = r.choices[0].message.content.strip().replace("```json", "").replace("```", "")
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Owner intent detection failed: {e}")
        return {"intent": "unknown"}


# ─── Handlers ─────────────────────────────────────────────────────────────────

async def _handle_stock_check(db: AsyncSession, store: Store, product_hint: str | None) -> str:
    """Retourne les niveaux de stock — filtré par produit si hint fourni."""
    q = select(Product).where(Product.store_id == store.id, Product.is_active)
    if product_hint:
        q = q.where(Product.name.ilike(f"%{product_hint}%"))
    q = q.order_by(Product.stock_qty.asc()).limit(20)

    result = await db.execute(q)
    products = result.scalars().all()

    if not products:
        hint = f' pour "{product_hint}"' if product_hint else ""
        return f"❌ Aucun produit trouvé{hint}."

    lines = ["📦 *Stock actuel* :", ""]
    low_stock = []
    for p in products:
        stock_val = p.stock_qty if p.stock_qty is not None else 0
        icon = "🔴" if stock_val == 0 else ("🟡" if stock_val <= 5 else "🟢")
        price_str = f" | {p.price:.3f} DT" if p.price else ""
        lines.append(f"{icon} *{p.name}* : {stock_val} unités{price_str}")
        if stock_val <= 5:
            low_stock.append(p.name)

    if low_stock:
        lines.append("")
        lines.append(f"⚠️ Stock bas : {', '.join(low_stock)}")

    return "\n".join(lines)


async def _handle_orders_summary(db: AsyncSession, store: Store, period: str) -> str:
    """Résumé des commandes selon la période."""
    tz_offset = timedelta(hours=1)  # Africa/Tunis UTC+1
    now_local = datetime.now(UTC) + tz_offset

    if period == "week":
        since = now_local - timedelta(days=7)
        period_label = "7 derniers jours"
    elif period == "month":
        since = now_local - timedelta(days=30)
        period_label = "30 derniers jours"
    else:
        since = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        period_label = "aujourd'hui"

    since_utc = since.replace(tzinfo=UTC) - tz_offset

    q = select(Order).where(
        Order.store_id == store.id,
        Order.created_at >= since_utc,
    )
    result = await db.execute(q)
    orders = result.scalars().all()

    if not orders:
        return f"📋 Aucune commande {period_label}."

    total_orders = len(orders)
    confirmed = [o for o in orders if o.status in (OrderStatus.CONFIRMED, OrderStatus.PAID, OrderStatus.DELIVERED)]
    pending = [o for o in orders if o.status == OrderStatus.PENDING]
    cancelled = [o for o in orders if o.status == OrderStatus.CANCELLED]
    revenue = sum(o.total_amount for o in confirmed if o.total_amount)

    lines = [
        f"📋 *Commandes — {period_label}* :",
        "",
        f"📦 Total : *{total_orders}* commandes",
        f"✅ Confirmées : *{len(confirmed)}*",
        f"⏳ En attente : *{len(pending)}*",
        f"❌ Annulées : *{len(cancelled)}*",
        f"💰 Chiffre d'affaires : *{revenue:.3f} DT*",
    ]

    # Top 3 produits vendus
    product_counts: dict = {}
    for o in confirmed:
        if o.items:
            for item in (o.items if isinstance(o.items, list) else []):
                name = item.get("product_name", "?") if isinstance(item, dict) else str(item)
                product_counts[name] = product_counts.get(name, 0) + 1

    if product_counts:
        top3 = sorted(product_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        lines.append("")
        lines.append("🏆 Top produits :")
        for name, qty in top3:
            lines.append(f"  • {name} : {qty}x")

    return "\n".join(lines)


async def _handle_clients_stats(db: AsyncSession, store: Store) -> str:
    """Stats clients du store."""
    total_result = await db.execute(
        select(func.count()).where(Customer.store_id == store.id)
    )
    total = total_result.scalar() or 0

    # Clients actifs (message dans les 30 derniers jours)
    since_30 = datetime.now(UTC) - timedelta(days=30)
    active_result = await db.execute(
        select(func.count(func.distinct(WhatsAppMessage.from_phone))).where(
            WhatsAppMessage.store_id == store.id,
            WhatsAppMessage.created_at >= since_30,
        )
    )
    active = active_result.scalar() or 0

    # Clients avec au moins une commande
    buyers_result = await db.execute(
        select(func.count(func.distinct(Order.customer_id))).where(
            Order.store_id == store.id,
            Order.status.notin_([OrderStatus.CANCELLED]),
        )
    )
    buyers = buyers_result.scalar() or 0

    conversion = round((buyers / total * 100), 1) if total > 0 else 0

    return (
        f"👥 *Statistiques clients* :\n\n"
        f"📊 Total clients : *{total}*\n"
        f"✅ Actifs (30j) : *{active}*\n"
        f"🛒 Ont commandé : *{buyers}*\n"
        f"📈 Taux conversion : *{conversion}%*"
    )


async def _handle_daily_report(db: AsyncSession, store: Store) -> str:
    """Rapport complet du jour."""
    stock_msg = await _handle_stock_check(db, store, None)
    orders_msg = await _handle_orders_summary(db, store, "today")
    clients_msg = await _handle_clients_stats(db, store)

    return (
        f"📊 *Rapport du jour — {store.name}*\n"
        f"{'─' * 28}\n\n"
        f"{orders_msg}\n\n"
        f"{'─' * 28}\n\n"
        f"{clients_msg}\n\n"
        f"{'─' * 28}\n\n"
        f"{stock_msg}"
    )


async def _handle_set_stock_alert(
    db: AsyncSession, store: Store, threshold: int
) -> str:
    """Stocke l'alerte stock dans le JSON config du store."""
    # On utilise un champ JSON existant : payment_config (on ajoute une clé admin_alerts)
    config = store.payment_config or {}
    config["stock_alert_threshold"] = threshold
    store.payment_config = config
    await db.commit()
    return (
        f"🔔 Alerte configurée : vous serez notifié quand un produit "
        f"passe sous *{threshold} unités*.\n"
        f"Vérification automatique à chaque mise à jour de stock."
    )


async def _handle_broadcast(
    db: AsyncSession,
    store: Store,
    wa: WhatsAppClient,
    message: str,
    confirmed: bool,
    from_phone: str,
    owner_state: dict,
) -> str:
    """Broadcast message -> tous les clients actifs du store (avec confirmation)."""
    if not confirmed:
        # Demander confirmation
        since_90 = datetime.now(UTC) - timedelta(days=90)
        count_result = await db.execute(
            select(func.count(Customer.id)).where(
                Customer.store_id == store.id,
                Customer.last_message_at >= since_90,
                Customer.whatsapp_phone != from_phone,  # Exclure le marchand
                Customer.opted_out.is_(False),
            )
        )
        count = count_result.scalar() or 0
        count = min(count, 500)  # Cap sécurité

        owner_state["pending_broadcast"] = message
        return (
            f"📢 *Broadcast en attente de confirmation*\n\n"
            f"Message : _{message}_\n\n"
            f"👥 Destinataires : *{count} clients* actifs (90 jours)\n\n"
            f"⚠️ Répondez *OUI* pour confirmer ou *NON* pour annuler."
        )

    # Broadcast confirmé
    pending_msg = owner_state.pop("pending_broadcast", message)
    since_90 = datetime.now(UTC) - timedelta(days=90)

    phones_result = await db.execute(
        select(Customer.whatsapp_phone).where(
            Customer.store_id == store.id,
            Customer.last_message_at >= since_90,
            Customer.whatsapp_phone != from_phone,
            Customer.opted_out.is_(False),
        ).limit(500)
    )
    phones = [row[0] for row in phones_result.fetchall()]

    sent = 0
    failed = 0
    # FIX A: Rate limiting anti-suspension Meta.
    # Meta limite à ~80 msg/min par numéro sur les BSP standards.
    # On envoie 1 msg/sec max (60/min) + pause 2s toutes les 50 msgs.
    # Sans ça : 500 msgs en rafale -> suspension compte WhatsApp Business.
    import asyncio as _asyncio
    for i, phone in enumerate(phones):
        try:
            await wa.send_text(phone, pending_msg)
            sent += 1
        except Exception as e:
            logger.warning("Broadcast failed for %s: %s", phone[:6] + "***", e)
            failed += 1

        # 1 msg/sec
        await _asyncio.sleep(1.0)
        # Pause 2s tous les 50 msgs (laisse le time bucket se vider)
        if (i + 1) % 50 == 0:
            logger.info("Broadcast pause store=%s sent=%d/%d", store.id, sent, len(phones))
            await _asyncio.sleep(2.0)

    return (
        f"📢 *Broadcast envoyé !*\n\n"
        f"✅ Envoyé : *{sent}* clients\n"
        f"❌ Échecs : *{failed}*\n\n"
        f"Message : _{pending_msg}_"
    )


def _help_message() -> str:
    return (
        "🤖 *Commandes disponibles* :\n\n"
        "📦 `stock` — voir tout le stock\n"
        "📦 `stock t-shirt` — stock d'un produit\n"
        "📋 `commandes` — résumé du jour\n"
        "📋 `commandes semaine` — 7 derniers jours\n"
        "📊 `rapport` — rapport complet du jour\n"
        "👥 `clients` — statistiques clients\n"
        "📢 `broadcast <votre message>` — envoyer à tous\n"
        "🔔 `alerte stock 5` — alerte si stock < N\n"
        "❓ `aide` — cette liste\n\n"
        "_Vous pouvez écrire en français, arabe ou darija._"
    )


# ─── Main entry point ─────────────────────────────────────────────────────────

async def handle_owner_message(
    db: AsyncSession,
    store: Store,
    message: str,
    wa: WhatsAppClient,
    from_phone: str,
) -> str:
    """
    Point d'entrée pour les messages du marchand (mode admin conversationnel).
    Appelé uniquement si from_phone == store.whatsapp_phone.
    """
    # Récupérer/initialiser l'état owner depuis Redis ou un dict store-level
    # Ici on utilise le JSON config du store comme stockage léger (owner_session)
    config = store.payment_config or {}
    owner_state: dict = config.get("owner_session", {})

    text = message.strip()
    text_lower = text.lower()

    # ── Confirmation broadcast en attente ─────────────────────────────────────
    if owner_state.get("pending_broadcast"):
        confirm_yes = {"oui", "yes", "نعم", "aywa", "ok", "confirm", "يا"}
        confirm_no  = {"non", "no", "لا", "annuler", "cancel"}
        if any(w in text_lower for w in confirm_yes):
            reply = await _handle_broadcast(
                db, store, wa, "", True, from_phone, owner_state
            )
        elif any(w in text_lower for w in confirm_no):
            owner_state.pop("pending_broadcast", None)
            reply = "❌ Broadcast annulé."
        else:
            reply = (
                "⚠️ Broadcast en attente.\n"
                "Répondez *OUI* pour confirmer ou *NON* pour annuler."
            )
        # Sauvegarder state
        config["owner_session"] = owner_state
        store.payment_config = config
        await db.commit()
        await wa.send_text(from_phone, reply)
        return reply

    # ── Intent detection ──────────────────────────────────────────────────────
    intent_data = await _detect_owner_intent(text, tenant_id=store.id)
    intent = intent_data.get("intent", "unknown")

    if intent == "stock_check":
        reply = await _handle_stock_check(db, store, intent_data.get("product_hint"))

    elif intent == "orders_summary":
        period = intent_data.get("period") or "today"
        reply = await _handle_orders_summary(db, store, period)

    elif intent == "clients_stats":
        reply = await _handle_clients_stats(db, store)

    elif intent == "daily_report":
        reply = await _handle_daily_report(db, store)

    elif intent == "broadcast":
        broadcast_msg = intent_data.get("broadcast_msg") or text
        # Nettoyer le préfixe "broadcast" du message
        for prefix in ["broadcast ", "envoyer ", "send "]:
            if broadcast_msg.lower().startswith(prefix):
                broadcast_msg = broadcast_msg[len(prefix):]
        reply = await _handle_broadcast(
            db, store, wa, broadcast_msg, False, from_phone, owner_state
        )
        # Stocker le pending broadcast dans le state
        config["owner_session"] = owner_state
        store.payment_config = config
        await db.commit()

    elif intent == "set_stock_alert":
        threshold = intent_data.get("threshold") or 5
        reply = await _handle_set_stock_alert(db, store, int(threshold))

    elif intent == "cancel_broadcast":
        owner_state.pop("pending_broadcast", None)
        config["owner_session"] = owner_state
        store.payment_config = config
        await db.commit()
        reply = "❌ Broadcast annulé."

    elif intent == "help":
        reply = _help_message()

    else:
        # Commande non reconnue — afficher l'aide
        reply = (
            "❓ Commande non reconnue.\n\n"
            + _help_message()
        )

    await wa.send_text(from_phone, reply)
    return reply
