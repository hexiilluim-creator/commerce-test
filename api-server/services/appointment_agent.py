"""
appointment_agent.py — Agent FSM WhatsApp pour la gestion des RDV
==================================================================
FSM States:
  IDLE -> SERVICE_SELECTION -> DATE_SELECTION -> TIME_SELECTION
       -> AWAITING_CONFIRM -> APPOINTMENT_BOOKED

Fonctionnalités:
  - Détection d'intention RDV (texte + vocal via Whisper)
  - Listing des services disponibles
  - Calcul dynamique des créneaux libres selon les règles de dispo
  - Confirmation + message WA formaté
  - Rappel automatique 24h avant (tâche Celery)
  - Support darija / arabe / français / anglais
"""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import (
    Appointment,
    AppointmentStatus,
    AvailabilityException,
    AvailabilityRule,
    BusinessConfig,
    Customer,
    Service,
    Store,
)
from services.llm_gateway import chat as llm_chat
from utils.whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)

# ─── FSM States ───────────────────────────────────────────────────────────────
class AptState:
    IDLE             = "apt_idle"
    SERVICE_SELECT   = "apt_service_select"
    DATE_SELECT      = "apt_date_select"
    TIME_SELECT      = "apt_time_select"
    AWAIT_CONFIRM    = "apt_await_confirm"
    BOOKED           = "apt_booked"


# ─── Intent detection prompt ──────────────────────────────────────────────────
APT_INTENT_PROMPT = """Analyse le message pour un système de prise de RDV.
Le client peut parler en français, arabe classique ou darija tunisienne.

Retourne UNIQUEMENT un JSON valide:
{
  "intent": "book_appointment | cancel_appointment | reschedule | check_appointment | greeting | other",
  "service_hint": "terme mentionné ou null",
  "date_hint": "date mentionnée en clair ou null",
  "time_hint": "heure mentionnée ou null",
  "name_hint": "prénom/nom mentionné ou null",
  "language": "fr | ar | darija"
}"""


async def detect_apt_intent(message: str, tenant_id: int | None = None) -> dict:
    try:
        r = await llm_chat(
            model=settings.OPENAI_MODEL,
            max_tokens=180,
            tenant_id=tenant_id,
            agent_name="appointment_agent.intent",
            channel="whatsapp",
            messages=[
                {"role": "system", "content": APT_INTENT_PROMPT},
                {"role": "user", "content": message},
            ],
        )
        raw = r.choices[0].message.content.strip().replace("```json", "").replace("```", "")
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"APT intent detection failed: {e}")
        return {"intent": "other", "language": "fr"}


# ─── Slot calculator ──────────────────────────────────────────────────────────
DAY_MAP = {
    0: "monday", 1: "tuesday", 2: "wednesday", 3: "thursday",
    4: "friday", 5: "saturday", 6: "sunday",
}


async def get_available_slots(
    db: AsyncSession,
    store: Store,
    target_date: date,
    service: Service | None = None,
) -> list[str]:
    """
    Retourne la liste des créneaux libres pour une date donnée.
    Format: ["09:00", "09:30", "10:00", ...]
    """
    tz = ZoneInfo(store.timezone or "Africa/Tunis")
    day_name = DAY_MAP[target_date.weekday()]

    # 1. Vérifier les exceptions (fermetures)
    exc_result = await db.execute(
        select(AvailabilityException).where(
            AvailabilityException.store_id == store.id,
            AvailabilityException.date == target_date.isoformat(),
            AvailabilityException.is_closed,
        )
    )
    if exc_result.scalar_one_or_none():
        return []  # Fermé ce jour

    # 2. Charger les règles de dispo du jour
    rules_result = await db.execute(
        select(AvailabilityRule).where(
            AvailabilityRule.store_id == store.id,
            AvailabilityRule.day_of_week == day_name,
            AvailabilityRule.is_active,
        )
    )
    rules = rules_result.scalars().all()
    if not rules:
        return []

    # 3. Charger les RDV déjà pris ce jour
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=tz)
    day_end   = day_start + timedelta(days=1)
    booked_result = await db.execute(
        select(Appointment).where(
            Appointment.store_id == store.id,
            Appointment.scheduled_at >= day_start,
            Appointment.scheduled_at < day_end,
            Appointment.status.notin_([AppointmentStatus.CANCELLED]),
        )
    )
    booked_times = {
        appt.scheduled_at.astimezone(tz).strftime("%H:%M")
        for appt in booked_result.scalars().all()
    }

    # 4. Générer les créneaux selon les règles + durée service
    slot_duration = service.duration_min if service else 30
    config_result = await db.execute(
        select(BusinessConfig).where(BusinessConfig.store_id == store.id)
    )
    config = config_result.scalar_one_or_none()
    if config:
        slot_duration = service.duration_min if service else config.default_slot_duration_min

    # Lead time : pas de RDV dans les N prochaines heures
    lead_hours = config.booking_lead_time_hours if config else 1
    now_tz = datetime.now(tz)
    min_bookable = now_tz + timedelta(hours=lead_hours)

    slots = []
    for rule in rules:
        h_start, m_start = map(int, rule.start_time.split(":"))
        h_end,   m_end   = map(int, rule.end_time.split(":"))
        current = datetime.combine(target_date, datetime.min.time()).replace(
            hour=h_start, minute=m_start, tzinfo=tz
        )
        end_dt = datetime.combine(target_date, datetime.min.time()).replace(
            hour=h_end, minute=m_end, tzinfo=tz
        )
        while current + timedelta(minutes=slot_duration) <= end_dt:
            slot_str = current.strftime("%H:%M")
            if slot_str not in booked_times and current >= min_bookable:
                slots.append(slot_str)
            current += timedelta(minutes=slot_duration)

    return slots


# ─── Natural language date parser ─────────────────────────────────────────────
async def parse_date_nl(text: str, tz_str: str = "Africa/Tunis", tenant_id: int | None = None) -> date | None:
    """Parse une date en langage naturel (demain, vendredi, 5 mai...) -> date ISO."""
    tz = ZoneInfo(tz_str)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    try:
        r = await llm_chat(
            model=settings.OPENAI_MODEL,
            max_tokens=30,
            tenant_id=tenant_id,
            agent_name="appointment_agent.date_parser",
            channel="whatsapp",
            messages=[
                {"role": "system", "content": f"Aujourd'hui est {today_str}. Retourne UNIQUEMENT la date ISO 8601 (YYYY-MM-DD) correspondant au texte ci-dessous. Si impossible, retourne 'null'."},
                {"role": "user", "content": text},
            ],
        )
        raw = r.choices[0].message.content.strip().replace('"', '').replace("'", "")
        if raw == "null" or not raw:
            return None
        return date.fromisoformat(raw)
    except Exception as _exc:
        logger.warning("parse_date_nl failed: %s", _exc)
        return None


# ─── Message formatters ───────────────────────────────────────────────────────
def _lang_templates(lang: str) -> dict:
    if lang in ("ar", "darija"):
        return {
            "welcome":       "مرحباً! 🗓️ أهلاً بك في نظام الحجز. اختر الخدمة التي تريد حجزها:",
            "choose_date":   "✅ رائع! اختر تاريخ الموعد (مثال: غداً، الجمعة، 5 ماي):",
            "choose_time":   "📅 المواعيد المتاحة ليوم {date}:\n{slots}\n\nأدخل الوقت الذي يناسبك:",
            "no_slots":      "😕 لا توجد مواعيد متاحة في هذا اليوم. جرّب يوماً آخر.",
            "confirm":       "🗓️ تأكيد الموعد:\n• الخدمة: {service}\n• التاريخ: {date}\n• الوقت: {time}\n\nهل تؤكد؟ (نعم / لا)",
            "booked":        "✅ تم حجز موعدك بنجاح!\n• {service}\n• {date} ⏰ {time}\nسنرسل لك تذكيراً قبل 24 ساعة. 🔔",
            "cancelled":     "❌ تم إلغاء حجزك. يمكنك الحجز من جديد في أي وقت.",
            "no_services":   "عذراً، لا توجد خدمات متاحة حالياً.",
        }
    else:
        return {
            "welcome":       "Bonjour ! 🗓️ Bienvenue dans notre système de réservation.\nQuel service souhaitez-vous réserver ?",
            "choose_date":   "✅ Parfait ! Pour quelle date souhaitez-vous votre RDV ?\n(Ex: demain, vendredi, 5 mai)",
            "choose_time":   "📅 Créneaux disponibles le {date} :\n{slots}\n\nEntrez l'heure qui vous convient :",
            "no_slots":      "😕 Aucun créneau disponible ce jour-là. Essayez une autre date.",
            "confirm":       "🗓️ Récapitulatif de votre RDV :\n• Service : {service}\n• Date : {date}\n• Heure : {time}\n\nConfirmez-vous ? (oui / non)",
            "booked":        "✅ Votre RDV est confirmé !\n• {service}\n• {date} à {time}\nUn rappel vous sera envoyé 24h avant. 🔔",
            "cancelled":     "❌ Réservation annulée. Vous pouvez reprendre à tout moment.",
            "no_services":   "Désolé, aucun service disponible pour le moment.",
        }


# ─── Main handler ─────────────────────────────────────────────────────────────
async def handle_appointment_message(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    message: str,
    wa: WhatsAppClient,
) -> str:
    """
    Point d'entrée unique pour le mode RDV.
    Gère le FSM complet et retourne la réponse envoyée.
    """
    state: dict = customer.conversation_state or {}
    apt_state = state.get("apt_fsm", AptState.IDLE)
    lang = customer.language or store.language or "fr"
    T = _lang_templates(lang)
    phone = customer.whatsapp_phone

    intent_data = await detect_apt_intent(message, tenant_id=store.id)
    intent = intent_data.get("intent", "other")

    # ── Annulation en cours de flow ────────────────────────────────────────────
    cancel_words = {"non", "no", "لا", "annuler", "cancel", "waqef", "wakef"}
    if message.lower().strip() in cancel_words and apt_state != AptState.IDLE:
        state["apt_fsm"] = AptState.IDLE
        customer.conversation_state = state
        await db.commit()
        reply = T["cancelled"]
        await wa.send_text(phone, reply)
        return reply

    # ── IDLE : déclenchement RDV ───────────────────────────────────────────────
    if apt_state == AptState.IDLE or intent == "book_appointment":
        services_result = await db.execute(
            select(Service).where(
                Service.store_id == store.id,
                Service.is_active,
            )
        )
        services = services_result.scalars().all()

        if not services:
            await wa.send_text(phone, T["no_services"])
            return T["no_services"]

        # Stocker la liste en state
        state["apt_fsm"] = AptState.SERVICE_SELECT
        state["apt_services"] = {str(s.id): {"name": s.name, "duration": s.duration_min, "price": s.price} for s in services}
        customer.conversation_state = state
        await db.commit()

        lines = [T["welcome"], ""]
        for i, s in enumerate(services, 1):
            price_str = f" — {s.price:.3f} DT" if s.price else ""
            lines.append(f"{i}. {s.name} ({s.duration_min} min{price_str})")
        reply = "\n".join(lines)
        await wa.send_text(phone, reply)
        return reply

    # ── SERVICE_SELECT ─────────────────────────────────────────────────────────
    if apt_state == AptState.SERVICE_SELECT:
        services_map: dict = state.get("apt_services", {})
        chosen_service_id = None

        # Essai par numéro
        if message.strip().isdigit():
            idx = int(message.strip())
            keys = list(services_map.keys())
            if 1 <= idx <= len(keys):
                chosen_service_id = keys[idx - 1]
        else:
            # Essai par nom (fuzzy partiel)
            msg_lower = message.lower()
            for sid, sdata in services_map.items():
                if sdata["name"].lower() in msg_lower or msg_lower in sdata["name"].lower():
                    chosen_service_id = sid
                    break

        if not chosen_service_id:
            # Re-lister
            lines = ["❓ " + ("الخدمة غير موجودة. حاول مجدداً:" if lang in ("ar","darija") else "Service introuvable. Choisissez parmi :"), ""]
            for i, (sid, sd) in enumerate(services_map.items(), 1):
                lines.append(f"{i}. {sd['name']}")
            reply = "\n".join(lines)
            await wa.send_text(phone, reply)
            return reply

        state["apt_service_id"] = chosen_service_id
        state["apt_fsm"] = AptState.DATE_SELECT
        customer.conversation_state = state
        await db.commit()

        reply = T["choose_date"]
        await wa.send_text(phone, reply)
        return reply

    # ── DATE_SELECT ────────────────────────────────────────────────────────────
    if apt_state == AptState.DATE_SELECT:
        tz_str = store.timezone or "Africa/Tunis"
        parsed_date = await parse_date_nl(message, tz_str, tenant_id=store.id)

        if not parsed_date:
            hint = "أرسل التاريخ بوضوح (مثال: غداً، الجمعة)" if lang in ("ar","darija") else "Envoyez une date claire (ex: demain, vendredi, 5 mai)"
            await wa.send_text(phone, f"❓ {hint}")
            return hint

        # Vérifier que la date n'est pas dans le passé
        tz = ZoneInfo(tz_str)
        if parsed_date < datetime.now(tz).date():
            msg = "لا يمكن حجز موعد في الماضي." if lang in ("ar","darija") else "Impossible de réserver dans le passé."
            await wa.send_text(phone, msg)
            return msg

        # Charger le service pour la durée
        service_id = state.get("apt_service_id")
        service = None
        if service_id:
            svc_result = await db.execute(select(Service).where(Service.id == int(service_id)))
            service = svc_result.scalar_one_or_none()

        slots = await get_available_slots(db, store, parsed_date, service)

        if not slots:
            await wa.send_text(phone, T["no_slots"])
            return T["no_slots"]

        state["apt_date"] = parsed_date.isoformat()
        state["apt_slots"] = slots
        state["apt_fsm"] = AptState.TIME_SELECT
        customer.conversation_state = state
        await db.commit()

        date_display = parsed_date.strftime("%d/%m/%Y")
        slots_str = "\n".join([f"  • {s}" for s in slots])
        reply = T["choose_time"].format(date=date_display, slots=slots_str)
        await wa.send_text(phone, reply)
        return reply

    # ── TIME_SELECT ────────────────────────────────────────────────────────────
    if apt_state == AptState.TIME_SELECT:
        available_slots: list = state.get("apt_slots", [])
        chosen_time = None

        # Normaliser "9h30", "9:30", "930" -> "09:30"
        raw = message.strip().replace("h", ":").replace("H", ":").replace(" ", "")
        for slot in available_slots:
            if raw in (slot, slot.replace(":", ""), slot.lstrip("0")):
                chosen_time = slot
                break

        if not chosen_time:
            slots_str = "\n".join([f"  • {s}" for s in available_slots])
            hint = f"⏰ Créneaux disponibles :\n{slots_str}\n\nChoisissez un créneau exact."
            if lang in ("ar", "darija"):
                hint = f"⏰ المواعيد المتاحة :\n{slots_str}\n\nاختر وقتاً محدداً."
            await wa.send_text(phone, hint)
            return hint

        state["apt_time"] = chosen_time
        state["apt_fsm"] = AptState.AWAIT_CONFIRM
        customer.conversation_state = state
        await db.commit()

        service_name = state.get("apt_services", {}).get(state.get("apt_service_id", ""), {}).get("name", "RDV")
        date_display = state.get("apt_date", "")
        reply = T["confirm"].format(service=service_name, date=date_display, time=chosen_time)
        await wa.send_text(phone, reply)
        return reply

    # ── AWAIT_CONFIRM ──────────────────────────────────────────────────────────
    if apt_state == AptState.AWAIT_CONFIRM:
        confirm_words = {"oui", "yes", "نعم", "أيوه", "aywa", "iih", "ok", "ouais", "confirm", "yep"}
        if message.lower().strip() in confirm_words or any(w in message.lower() for w in confirm_words):

            # Créer le RDV en DB
            tz = ZoneInfo(store.timezone or "Africa/Tunis")
            apt_date = date.fromisoformat(state["apt_date"])
            h, m = map(int, state["apt_time"].split(":"))
            scheduled_at = datetime.combine(apt_date, datetime.min.time()).replace(
                hour=h, minute=m, tzinfo=tz
            )

            service_id = state.get("apt_service_id")
            service_obj = None
            if service_id:
                svc_result = await db.execute(select(Service).where(Service.id == int(service_id)))
                service_obj = svc_result.scalar_one_or_none()

            # FIX B: Distributed lock on time slot to prevent double-booking.
            # Without this, 2 clients confirming the same slot simultaneously
            # both pass the availability check -> 2 appointments at the same time.
            # Redis lock TTL = 10s (enough for DB write + commit).
            slot_lock_key = f"apt_slot:{store.id}:{apt_date}:{state['apt_time']}"
            try:
                from services.redis_lock import acquire_lock, release_lock
                lock_token = await acquire_lock(slot_lock_key, ttl=10)
                if not lock_token:
                    customer.conversation_state = state
                    await db.commit()
                    return (
                        "⚠️ Ce créneau vient d'être réservé par quelqu'un d'autre. "
                        "Tapez *DISPO* pour voir les créneaux disponibles."
                    )
            except Exception as _lock_err:
                logger.warning("apt slot lock unavailable: %s — proceeding without lock", _lock_err)
                lock_token = None

            # Vérification de disponibilité APRÈS acquisition du lock
            conflict = await db.execute(
                select(Appointment).where(
                    Appointment.store_id == store.id,
                    Appointment.scheduled_at == scheduled_at,
                    Appointment.status == AppointmentStatus.CONFIRMED,
                ).limit(1)
            )
            if conflict.scalar_one_or_none():
                if lock_token:
                    try:
                        await release_lock(slot_lock_key, lock_token)
                    except Exception as _exc:
                        logger.warning("operation failed: %s", _exc)
                        pass
                return (
                    "⚠️ Ce créneau vient d'être réservé. "
                    "Tapez *DISPO* pour voir les créneaux disponibles."
                )

            appointment = Appointment(
                store_id=store.id,
                customer_id=customer.id,
                service_id=int(service_id) if service_id else None,
                status=AppointmentStatus.CONFIRMED,
                scheduled_at=scheduled_at,
                duration_min=service_obj.duration_min if service_obj else 30,
                patient_name=customer.name or customer.whatsapp_phone,
            )
            db.add(appointment)

            # Reset FSM
            state["apt_fsm"] = AptState.BOOKED
            state.pop("apt_services", None)
            state.pop("apt_slots", None)
            customer.conversation_state = state
            await db.flush()
            await db.commit()

            # Relâcher le lock après commit
            if lock_token:
                try:
                    await release_lock(slot_lock_key, lock_token)
                except Exception as _exc:
                    logger.warning("operation failed: %s", _exc)
                    pass

            # Planifier le rappel 24h avant
            try:
                from services.tasks import send_appointment_reminder
                reminder_time = scheduled_at - timedelta(hours=24)
                eta_seconds = max(0, int((reminder_time - datetime.now(UTC)).total_seconds()))
                send_appointment_reminder.apply_async(
                    args=[appointment.id],
                    countdown=eta_seconds,
                )
            except Exception as e:
                logger.warning(f"Could not schedule reminder: {e}")

            service_name = service_obj.name if service_obj else "RDV"
            reply = T["booked"].format(
                service=service_name,
                date=apt_date.strftime("%d/%m/%Y"),
                time=state["apt_time"],
            )
            # Reset FSM state après booking
            state["apt_fsm"] = AptState.IDLE
            customer.conversation_state = state
            await db.commit()

            await wa.send_text(phone, reply)
            return reply

        else:
            # Non-confirmation -> annulation
            state["apt_fsm"] = AptState.IDLE
            customer.conversation_state = state
            await db.commit()
            reply = T["cancelled"]
            await wa.send_text(phone, reply)
            return reply

    # Fallback
    fallback = "Tapez 'RDV' pour prendre un rendez-vous." if lang not in ("ar","darija") else "اكتب 'موعد' لحجز موعد."
    await wa.send_text(phone, fallback)
    return fallback
