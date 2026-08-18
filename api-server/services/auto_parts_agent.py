
# AUDIT FIX: Les appels LLM doivent transiter par llm_gateway (facturation, BYOK, quotas tenant).
# L'utilisation directe de get_platform_client() contournait ces mécanismes.
from services import llm_gateway

"""
auto_parts_agent.py — Agent FSM WhatsApp pour vendeur de pièces auto
=====================================================================

FSM States :
  IDLE
    -> COLLECTING_VEHICLE   (on demande la carte grise ou les infos)
    -> COLLECTING_PART      (on demande la pièce recherchée)
    -> OEM_LOOKUP           (lookup OEM en cours)
    -> SHOWING_RESULTS      (résultats affichés, attente commande)
    -> AWAITING_CONFIRM     (client confirme la commande)
    -> DONE

Déclencheurs d'entrée dans le flow auto :
  - Client envoie photo carte grise (type=image)
  - Client mentionne "pièce", "filtre", "plaquette", etc.
  - store.auto_parts_mode = True (toutes les conversations -> flow auto)
"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import Customer, Store
from services.oem_lookup import OemResult, lookup_oem_reference
from services.stock_resolver import StockItem, resolve_stock
from services.vin_decoder import VehicleInfo, extract_from_image, extract_from_text
from utils.whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)
# Client OpenAI résolu à la demande via BYOK helper (par tenant courant).


# ─── FSM States ───────────────────────────────────────────────────────────────
class AptState:
    IDLE              = "auto_idle"
    COLLECT_VEHICLE   = "auto_collect_vehicle"
    COLLECT_PART      = "auto_collect_part"
    OEM_LOOKUP        = "auto_oem_lookup"
    SHOW_RESULTS      = "auto_show_results"
    AWAIT_CONFIRM     = "auto_await_confirm"
    DONE              = "auto_done"


# ─── Part intent detection ────────────────────────────────────────────────────
PART_DETECT_PROMPT = """Analyse ce message d'un client dans un magasin de pièces auto.
Le texte peut être en français, arabe, darija tunisienne.

Retourne UNIQUEMENT un JSON valide :
{
  "is_auto_parts_request": true/false,
  "part_query": "pièce demandée en français ou null",
  "vehicle_hint": "infos véhicule mentionnées ou null",
  "language": "fr | ar | darija"
}

Exemples auto : "filtre huile", "plaquettes de frein", "courroie distribution",
"فلتر الزيت", "plastik bab", "batterie clio", "amortisseur avant 206"
"""


async def detect_part_intent(text: str, store_id: int | None = None) -> dict:
    # AUDIT FIX: Appel LLM routé via llm_gateway pour respecter BYOK, quotas et facturation tenant.
    try:
        r = await llm_gateway.chat(
            messages=[
                {"role": "system", "content": PART_DETECT_PROMPT},
                {"role": "user", "content": text},
            ],
            tenant_id=store_id,
            agent_name="auto_parts_intent",
            max_tokens=150,
            temperature=0,
        )
        raw = r.choices[0].message.content.strip().replace("```json","").replace("```","")
        return json.loads(raw)
    except Exception as _exc:
        logger.warning("detect_part_intent failed: %s", _exc)
        return {"is_auto_parts_request": False, "language": "fr"}


# ─── Language templates ───────────────────────────────────────────────────────
def T(lang: str) -> dict:
    if lang in ("ar", "darija"):
        return {
            "ask_vehicle":    "🚗 مرحباً! أرسل لي صورة الكارت الرمادي أو أخبرني:\n• الماركة والموديل\n• سنة الصنع\n• نوع المحرك",
            "ask_part":       "✅ تمام، {vehicle}\n\nما هي القطعة التي تريدها؟",
            "looking_up":     "🔍 جاري البحث عن الأجزاء المتوافقة...",
            "found":          "🔎 *نتائج البحث لـ {part}*\n*السيارة:* {vehicle}\n\n{results}",
            "not_found":      "😕 لم أجد *{part}* في المخزن لـ {vehicle}.\n\nهل تريد طلب عرض سعر؟ (نعم / لا)",
            "confirm_order":  "🛒 *تأكيد الطلب:*\n• {item}\n• السعر: {price} دت\n\nتأكيد؟ (نعم / لا)",
            "ordered":        "✅ تم تسجيل طلبك! سنتواصل معك قريباً.",
            "cancelled":      "❌ تم الإلغاء. يمكنك طلب قطعة أخرى في أي وقت.",
            "vehicle_unclear":"❓ لم أتمكن من التعرف على السيارة. أرسل صورة الكارت الرمادي أو اكتب:\n_ماركة / موديل / سنة_",
            "no_vin_image":   "الصورة غير واضحة. حاول مرة أخرى أو اكتب معلومات السيارة.",
        }
    else:
        return {
            "ask_vehicle":    "🚗 Bonjour ! Envoyez-moi la photo de votre *carte grise* ou précisez :\n• Marque et modèle\n• Année\n• Motorisation",
            "ask_part":       "✅ Parfait, {vehicle}\n\nQuelle pièce recherchez-vous ?",
            "looking_up":     "🔍 Recherche des références en cours...",
            "found":          "🔎 *Résultats pour {part}*\n*Véhicule :* {vehicle}\n\n{results}",
            "not_found":      "😕 *{part}* non trouvé en stock pour {vehicle}.\n\nSouhaitez-vous un devis ? (oui / non)",
            "confirm_order":  "🛒 *Confirmation commande :*\n• {item}\n• Prix : {price} DT\n\nConfirmer ? (oui / non)",
            "ordered":        "✅ Commande enregistrée ! Nous vous contactons bientôt.",
            "cancelled":      "❌ Annulé. Vous pouvez chercher une autre pièce à tout moment.",
            "vehicle_unclear":"❓ Impossible d'identifier le véhicule. Envoyez la photo carte grise ou tapez :\n_Marque / Modèle / Année_",
            "no_vin_image":   "Image floue ou illisible. Réessayez ou saisissez les infos manuellement.",
        }


# ─── Result formatter ─────────────────────────────────────────────────────────
def format_results(
    items: list[StockItem],
    oem_result: OemResult | None,
    part_query: str,
    vehicle_summary: str,
) -> str:
    lines = []

    # Refs OEM trouvées
    if oem_result and oem_result.references:
        lines.append("📋 *Références OEM identifiées :*")
        for r in oem_result.references[:3]:
            lines.append(f"  • `{r['ref']}` — {r.get('brand','')}")
        if oem_result.warning:
            lines.append(f"\n{oem_result.warning}")
        lines.append("")

    # Stock
    if items:
        lines.append("📦 *Disponibilité en stock :*")
        for item in items[:6]:
            lines.append(item.format_wa())
    else:
        lines.append("⚠️ Aucune pièce trouvée dans le stock actuel.")

    return "\n".join(lines)


# ─── Main handler ─────────────────────────────────────────────────────────────
async def handle_auto_parts_message(
    db: AsyncSession,
    store: Store,
    customer: Customer,
    payload: dict,
    wa: WhatsAppClient,
) -> str:
    """
    Point d'entrée unique pour le flow pièces auto.
    payload contient : type, body, media_id (si image), transcribed_text (si audio)
    """
    state: dict = customer.conversation_state or {}
    fsm = state.get("auto_fsm", AptState.IDLE)
    lang = customer.language or store.language or "fr"
    t = T(lang)
    phone = customer.whatsapp_phone
    msg_type = payload.get("type", "text")

    # ── Décrypter les clés OEM ────────────────────────────────────────────────
    tecdoc_key, tecdoc_pid, autoiso_key = None, None, None
    if getattr(store, "tecdoc_api_key_enc", None):
        try:
            tecdoc_key = settings.decrypt(store.tecdoc_api_key_enc)
            tecdoc_pid = store.tecdoc_provider_id
        except Exception as _exc:
            logger.warning("handle_auto_parts_message failed: %s", _exc)
            pass
    if getattr(store, "autoiso_api_key_enc", None):
        try:
            autoiso_key = settings.decrypt(store.autoiso_api_key_enc)
        except Exception as _exc:
            logger.warning("handle_auto_parts_message failed: %s", _exc)
            pass

    # ── Annulation globale ────────────────────────────────────────────────────
    text = payload.get("body", payload.get("transcribed_text", "")).strip()
    cancel_words = {"annuler","cancel","recommencer","restart","لا","non","no"}
    if text.lower() in cancel_words and fsm != AptState.IDLE:
        state["auto_fsm"] = AptState.IDLE
        customer.conversation_state = state
        await db.commit()
        reply = t["cancelled"]
        await wa.send_text(phone, reply)
        return reply

    # ── IDLE : image carte grise ou texte pièce ───────────────────────────────
    if fsm == AptState.IDLE:
        vehicle_info: VehicleInfo | None = None

        if msg_type == "image" and payload.get("media_id"):
            # Télécharger et analyser l'image
            try:
                from services.voice_transcriber import _download_media
                image_bytes = await _download_media(payload["media_id"], store)
                vehicle_info = await extract_from_image(image_bytes, payload.get("mime_type","image/jpeg"))
            except Exception as e:
                logger.error(f"Image download for auto parts: {e}")

            if not vehicle_info or not vehicle_info.is_complete():
                reply = t["no_vin_image"] if not vehicle_info else t["vehicle_unclear"]
                state["auto_fsm"] = AptState.COLLECT_VEHICLE
                customer.conversation_state = state
                await db.commit()
                await wa.send_text(phone, reply)
                return reply

        elif text:
            # Détecter si c'est une demande de pièce avec infos véhicule
            intent = await detect_part_intent(text, store_id=store.id)
            if intent.get("vehicle_hint"):
                vehicle_info = await extract_from_text(intent["vehicle_hint"])

            if not vehicle_info or not vehicle_info.is_complete():
                # Pièce mentionnée mais pas le véhicule -> demander la carte grise
                if intent.get("is_auto_parts_request") and intent.get("part_query"):
                    state["auto_part_query"] = intent["part_query"]
                    state["auto_fsm"] = AptState.COLLECT_VEHICLE
                    customer.conversation_state = state
                    await db.commit()
                    reply = t["ask_vehicle"]
                    await wa.send_text(phone, reply)
                    return reply
                else:
                    # Ni pièce ni véhicule -> demander tout
                    state["auto_fsm"] = AptState.COLLECT_VEHICLE
                    customer.conversation_state = state
                    await db.commit()
                    reply = t["ask_vehicle"]
                    await wa.send_text(phone, reply)
                    return reply

        else:
            state["auto_fsm"] = AptState.COLLECT_VEHICLE
            customer.conversation_state = state
            await db.commit()
            reply = t["ask_vehicle"]
            await wa.send_text(phone, reply)
            return reply

        # Véhicule identifié -> stocker et demander la pièce
        state["auto_vehicle"] = vehicle_info.to_dict()
        if state.get("auto_part_query"):
            # Pièce déjà connue -> aller directement au lookup
            state["auto_fsm"] = AptState.OEM_LOOKUP
        else:
            state["auto_fsm"] = AptState.COLLECT_PART
        customer.conversation_state = state
        await db.commit()

        if state["auto_fsm"] == AptState.COLLECT_PART:
            reply = t["ask_part"].format(vehicle=vehicle_info.summary())
            await wa.send_text(phone, reply)
            return reply
        # Fall through to OEM_LOOKUP

    # ── COLLECT_VEHICLE ───────────────────────────────────────────────────────
    if fsm == AptState.COLLECT_VEHICLE:
        vehicle_info = None

        if msg_type == "image" and payload.get("media_id"):
            try:
                from services.voice_transcriber import _download_media
                image_bytes = await _download_media(payload["media_id"], store)
                vehicle_info = await extract_from_image(image_bytes)
            except Exception as e:
                logger.error(f"Image for vehicle: {e}")
        elif text:
            vehicle_info = await extract_from_text(text)

        if not vehicle_info or not vehicle_info.is_complete():
            reply = t["vehicle_unclear"]
            await wa.send_text(phone, reply)
            return reply

        state["auto_vehicle"] = vehicle_info.to_dict()
        state["auto_fsm"] = AptState.COLLECT_PART if not state.get("auto_part_query") else AptState.OEM_LOOKUP
        customer.conversation_state = state
        await db.commit()

        if state["auto_fsm"] == AptState.COLLECT_PART:
            reply = t["ask_part"].format(vehicle=vehicle_info.summary())
            await wa.send_text(phone, reply)
            return reply
        # Fall through

    # ── COLLECT_PART ──────────────────────────────────────────────────────────
    if fsm == AptState.COLLECT_PART:
        intent = await detect_part_intent(text, store_id=store.id)
        part_query = intent.get("part_query") or text
        state["auto_part_query"] = part_query
        state["auto_fsm"] = AptState.OEM_LOOKUP
        customer.conversation_state = state
        await db.commit()
        # Fall through to OEM_LOOKUP

    # ── OEM_LOOKUP ────────────────────────────────────────────────────────────
    if state.get("auto_fsm") == AptState.OEM_LOOKUP or fsm == AptState.OEM_LOOKUP:
        veh_data = state.get("auto_vehicle", {})
        part_query = state.get("auto_part_query", text)
        vehicle_info = VehicleInfo(**veh_data) if veh_data else VehicleInfo()

        # Notifier le client qu'on cherche
        await wa.send_text(phone, t["looking_up"])

        # Lookup OEM
        oem_result: OemResult | None = None
        if vehicle_info.make:
            oem_result = await lookup_oem_reference(
                make=vehicle_info.make or "",
                model=vehicle_info.model or "",
                year=vehicle_info.year or "",
                part_query=part_query,
                tecdoc_api_key=tecdoc_key,
                tecdoc_provider_id=tecdoc_pid,
                autoiso_api_key=autoiso_key,
            )

        # Résoudre le stock
        oem_refs = oem_result.best_refs() if oem_result else []
        part_kws = part_query.lower().split()
        vehicle_kws = [v for v in [vehicle_info.make, vehicle_info.model, vehicle_info.year] if v]

        stock_items = await resolve_stock(
            db, store, oem_refs, part_kws, vehicle_kws
        )

        # Formatter et répondre
        vehicle_summary = vehicle_info.summary()
        if stock_items or (oem_result and oem_result.references):
            results_str = format_results(stock_items, oem_result, part_query, vehicle_summary)
            reply = t["found"].format(
                part=part_query,
                vehicle=vehicle_summary,
                results=results_str,
            )
            # Stocker pour confirmation
            state["auto_stock_items"] = [
                {"name": i.name, "reference": i.reference, "price": i.price, "stock": i.stock_qty}
                for i in stock_items[:3]
            ]
            state["auto_fsm"] = AptState.SHOW_RESULTS
        else:
            reply = t["not_found"].format(part=part_query, vehicle=vehicle_summary)
            state["auto_fsm"] = AptState.IDLE  # Reset après not-found

        customer.conversation_state = state
        await db.commit()
        await wa.send_text(phone, reply)
        return reply

    # ── SHOW_RESULTS : client peut commander ─────────────────────────────────
    if fsm == AptState.SHOW_RESULTS:
        confirm_words = {"1","2","3","commander","oui","yes","نعم","aywa","ok","commande"}
        if any(w in text.lower() for w in confirm_words):
            items = state.get("auto_stock_items", [])
            # Prendre le premier item en stock
            chosen = next((i for i in items if i.get("stock", 0) != 0), items[0] if items else None)
            if chosen and chosen.get("price"):
                reply = t["confirm_order"].format(
                    item=chosen["name"],
                    price=f"{chosen['price']:.3f}",
                )
                state["auto_chosen_item"] = chosen
                state["auto_fsm"] = AptState.AWAIT_CONFIRM
            else:
                reply = t["not_found"].format(
                    part=state.get("auto_part_query","la pièce"),
                    vehicle=VehicleInfo(**state.get("auto_vehicle",{})).summary()
                )
                state["auto_fsm"] = AptState.IDLE
        else:
            # Nouvelle recherche
            state["auto_fsm"] = AptState.IDLE
            reply = t["ask_vehicle"]

        customer.conversation_state = state
        await db.commit()
        await wa.send_text(phone, reply)
        return reply

    # ── AWAIT_CONFIRM ─────────────────────────────────────────────────────────
    if fsm == AptState.AWAIT_CONFIRM:
        yes_words = {"oui","yes","نعم","aywa","ok","confirme","confirm"}
        if any(w in text.lower() for w in yes_words):
            # Créer la commande
            try:
                item_data = state.get("auto_chosen_item", {})
                # Simplification : on log la commande dans les messages
                logger.info(f"Auto parts order: store={store.id} customer={customer.id} item={item_data}")
            except Exception as e:
                logger.warning(f"Could not create order: {e}")

            state["auto_fsm"] = AptState.IDLE
            state.pop("auto_vehicle", None)
            state.pop("auto_part_query", None)
            state.pop("auto_stock_items", None)
            state.pop("auto_chosen_item", None)
            reply = t["ordered"]
        else:
            state["auto_fsm"] = AptState.IDLE
            reply = t["cancelled"]

        customer.conversation_state = state
        await db.commit()
        await wa.send_text(phone, reply)
        return reply

    # Fallback
    state["auto_fsm"] = AptState.IDLE
    customer.conversation_state = state
    await db.commit()
    reply = t["ask_vehicle"]
    await wa.send_text(phone, reply)
    return reply
