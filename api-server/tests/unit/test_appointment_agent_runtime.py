from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import appointment_agent


def test_appointment_states_and_templates():
    assert appointment_agent.AptState.IDLE == "apt_idle"
    assert "Bonjour" in appointment_agent._lang_templates("fr")["welcome"]
    assert "مرحباً" in appointment_agent._lang_templates("ar")["welcome"]


@pytest.mark.asyncio
async def test_detect_intent_and_parse_date_success_and_fallback():
    intent_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"intent":"book_appointment","language":"fr"}'))])
    date_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='2026-08-20'))])
    with patch("services.appointment_agent.llm_chat", new=AsyncMock(side_effect=[intent_response, date_response])):
        intent = await appointment_agent.detect_apt_intent("Je veux un rendez-vous", tenant_id=2)
        parsed = await appointment_agent.parse_date_nl("jeudi", tenant_id=2)
    assert intent["intent"] == "book_appointment"
    assert parsed == date(2026, 8, 20)

    with patch("services.appointment_agent.llm_chat", new=AsyncMock(side_effect=RuntimeError("offline"))):
        assert (await appointment_agent.detect_apt_intent("x"))["intent"] == "other"
        assert await appointment_agent.parse_date_nl("inconnu") is None


@pytest.mark.asyncio
async def test_available_slots_closed_and_no_rules():
    db = AsyncMock()
    closed = MagicMock(); closed.scalar_one_or_none.return_value = SimpleNamespace(id=1)
    db.execute.return_value = closed
    store = SimpleNamespace(id=1, timezone="Africa/Tunis")
    assert await appointment_agent.get_available_slots(db, store, date(2026, 8, 20)) == []

    no_rules = MagicMock(); no_rules.scalar_one_or_none.return_value = None; no_rules.scalars.return_value.all.return_value = []
    db.execute.return_value = no_rules
    assert await appointment_agent.get_available_slots(db, store, date(2026, 8, 20)) == []


def test_templates_cover_darija_alias():
    assert appointment_agent._lang_templates("darija")["confirm"]


@pytest.mark.asyncio
async def test_detect_intent_failure_returns_safe_fallback():
    with patch("services.appointment_agent.llm_chat", new=AsyncMock(side_effect=RuntimeError("offline"))):
        result = await appointment_agent.detect_apt_intent("bonjour")
    assert result == {"intent": "other", "language": "fr"}


@pytest.mark.asyncio
async def test_handle_appointment_idle_without_services_sends_safe_message():
    db = AsyncMock()
    result = MagicMock(); result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    db.commit = AsyncMock()
    wa = AsyncMock()
    store = SimpleNamespace(id=1, language="fr", timezone="Africa/Tunis")
    customer = SimpleNamespace(conversation_state={}, language="fr", whatsapp_phone="216000", id=9, name="Client")
    with patch.object(appointment_agent, "detect_apt_intent", new=AsyncMock(return_value={"intent": "book_appointment", "language": "fr"})):
        reply = await appointment_agent.handle_appointment_message(db, store, customer, "RDV", wa)
    assert "aucun service" in reply.lower()
    wa.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_appointment_service_selection_and_invalid_choice():
    db = AsyncMock(); db.commit = AsyncMock()
    service = SimpleNamespace(id=5, name="Diagnostic", duration_min=30, price=50.0)
    result = MagicMock(); result.scalars.return_value.all.return_value = [service]
    db.execute.return_value = result
    wa = AsyncMock()
    store = SimpleNamespace(id=1, language="fr", timezone="Africa/Tunis")
    customer = SimpleNamespace(conversation_state={"apt_fsm": appointment_agent.AptState.SERVICE_SELECT, "apt_services": {"5": {"name": "Diagnostic", "duration": 30, "price": 50.0}}}, language="fr", whatsapp_phone="216000", id=9, name="Client")
    with patch.object(appointment_agent, "detect_apt_intent", new=AsyncMock(return_value={"intent": "other", "language": "fr"})):
        invalid = await appointment_agent.handle_appointment_message(db, store, customer, "99", wa)
        chosen = await appointment_agent.handle_appointment_message(db, store, customer, "Diagnostic", wa)
    assert "introuvable" in invalid
    assert customer.conversation_state["apt_fsm"] == appointment_agent.AptState.DATE_SELECT
    assert "date" in chosen.lower()


@pytest.mark.asyncio
async def test_handle_appointment_date_and_time_invalid_paths():
    db = AsyncMock(); db.commit = AsyncMock()
    wa = AsyncMock()
    store = SimpleNamespace(id=1, language="fr", timezone="Africa/Tunis")
    customer = SimpleNamespace(conversation_state={"apt_fsm": appointment_agent.AptState.DATE_SELECT, "apt_service_id": "5"}, language="fr", whatsapp_phone="216000", id=9, name="Client")
    with patch.object(appointment_agent, "detect_apt_intent", new=AsyncMock(return_value={"intent": "other", "language": "fr"})), patch.object(appointment_agent, "parse_date_nl", new=AsyncMock(return_value=None)):
        reply = await appointment_agent.handle_appointment_message(db, store, customer, "date inconnue", wa)
    assert "date claire" in reply
    customer.conversation_state = {"apt_fsm": appointment_agent.AptState.TIME_SELECT, "apt_slots": ["09:00", "09:30"]}
    with patch.object(appointment_agent, "detect_apt_intent", new=AsyncMock(return_value={"intent": "other", "language": "fr"})):
        reply = await appointment_agent.handle_appointment_message(db, store, customer, "11:00", wa)
    assert "Créneaux disponibles" in reply


@pytest.mark.asyncio
async def test_handle_appointment_cancel_in_active_flow():
    db = AsyncMock(); db.commit = AsyncMock(); wa = AsyncMock()
    store = SimpleNamespace(id=1, language="fr", timezone="Africa/Tunis")
    customer = SimpleNamespace(conversation_state={"apt_fsm": appointment_agent.AptState.DATE_SELECT}, language="fr", whatsapp_phone="216000", id=9, name="Client")
    with patch.object(appointment_agent, "detect_apt_intent", new=AsyncMock(return_value={"intent": "other", "language": "fr"})):
        reply = await appointment_agent.handle_appointment_message(db, store, customer, "non", wa)
    assert customer.conversation_state["apt_fsm"] == appointment_agent.AptState.IDLE
    assert "annul" in reply.lower()


@pytest.mark.asyncio
async def test_handle_appointment_confirmation_rejects_locked_slot(monkeypatch):
    db = AsyncMock(); db.commit = AsyncMock()
    service_result = MagicMock(); service_result.scalar_one_or_none.return_value = SimpleNamespace(id=5, name="Diagnostic", duration_min=30)
    db.execute.return_value = service_result
    wa = AsyncMock()
    store = SimpleNamespace(id=1, language="fr", timezone="Africa/Tunis")
    customer = SimpleNamespace(
        conversation_state={"apt_fsm": appointment_agent.AptState.AWAIT_CONFIRM, "apt_date": "2099-08-20", "apt_time": "09:00", "apt_service_id": "5", "apt_services": {"5": {"name": "Diagnostic"}},},
        language="fr", whatsapp_phone="216000", id=9, name="Client",
    )
    acquire = AsyncMock(return_value=None)
    monkeypatch.setattr("services.redis_lock.acquire_lock", acquire)
    with patch.object(appointment_agent, "detect_apt_intent", new=AsyncMock(return_value={"intent": "other", "language": "fr"})):
        reply = await appointment_agent.handle_appointment_message(db, store, customer, "oui", wa)
    assert "réservé" in reply.lower()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_handle_appointment_date_valid_and_time_selection():
    db = MagicMock(); db.commit = AsyncMock()
    service_result = MagicMock(); service_result.scalar_one_or_none.return_value = SimpleNamespace(id=5, duration_min=30, name="Diagnostic")
    db.execute = AsyncMock(return_value=service_result)
    wa = AsyncMock()
    store = SimpleNamespace(id=1, language="fr", timezone="Africa/Tunis")
    customer = SimpleNamespace(conversation_state={"apt_fsm": appointment_agent.AptState.DATE_SELECT, "apt_service_id": "5"}, language="fr", whatsapp_phone="216", id=9, name="C" )
    with patch.object(appointment_agent, "detect_apt_intent", new=AsyncMock(return_value={"intent": "other", "language": "fr"})), \
         patch.object(appointment_agent, "parse_date_nl", new=AsyncMock(return_value=date(2099, 8, 20))), \
         patch.object(appointment_agent, "get_available_slots", new=AsyncMock(return_value=["09:00", "09:30"])):
        reply = await appointment_agent.handle_appointment_message(db, store, customer, "jeudi", wa)
    assert "Créneaux disponibles" in reply and customer.conversation_state["apt_fsm"] == appointment_agent.AptState.TIME_SELECT
    reply = await appointment_agent.handle_appointment_message(db, store, customer, "09:00", wa)
    assert "Récapitulatif" in reply and customer.conversation_state["apt_fsm"] == appointment_agent.AptState.AWAIT_CONFIRM


@pytest.mark.asyncio
async def test_handle_appointment_confirmation_success_and_conflict():
    db = MagicMock(); db.commit = AsyncMock(); db.flush = AsyncMock(); db.add = MagicMock()
    service_result = MagicMock(); service_result.scalar_one_or_none.return_value = SimpleNamespace(id=5, duration_min=30, name="Diagnostic")
    conflict_result = MagicMock(); conflict_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[service_result, conflict_result])
    wa = AsyncMock()
    store = SimpleNamespace(id=1, language="fr", timezone="Africa/Tunis")
    customer = SimpleNamespace(conversation_state={"apt_fsm": appointment_agent.AptState.AWAIT_CONFIRM, "apt_date": "2099-08-20", "apt_time": "09:00", "apt_service_id": "5", "apt_services": {"5": {"name": "Diagnostic"}}}, language="fr", whatsapp_phone="216", id=9, name="C")
    with patch.object(appointment_agent, "detect_apt_intent", new=AsyncMock(return_value={"intent": "other", "language": "fr"})), \
         patch("services.redis_lock.acquire_lock", new=AsyncMock(return_value="token")), \
         patch("services.redis_lock.release_lock", new=AsyncMock()), \
         patch("services.tasks.send_appointment_reminder", create=True):
        reply = await appointment_agent.handle_appointment_message(db, store, customer, "oui", wa)
    assert "confirmé" in reply and customer.conversation_state["apt_fsm"] == appointment_agent.AptState.IDLE
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_handle_appointment_confirmation_conflict_returns_safe_message():
    db = MagicMock(); db.commit = AsyncMock()
    service_result = MagicMock(); service_result.scalar_one_or_none.return_value = SimpleNamespace(id=5, duration_min=30, name="Diagnostic")
    conflict_result = MagicMock(); conflict_result.scalar_one_or_none.return_value = SimpleNamespace(id=99)
    db.execute = AsyncMock(side_effect=[service_result, conflict_result])
    wa = AsyncMock(); store = SimpleNamespace(id=1, language="fr", timezone="Africa/Tunis")
    customer = SimpleNamespace(conversation_state={"apt_fsm": appointment_agent.AptState.AWAIT_CONFIRM, "apt_date": "2099-08-20", "apt_time": "09:00", "apt_service_id": "5"}, language="fr", whatsapp_phone="216", id=9, name="C")
    with patch.object(appointment_agent, "detect_apt_intent", new=AsyncMock(return_value={"intent": "other", "language": "fr"})), \
         patch("services.redis_lock.acquire_lock", new=AsyncMock(return_value="t")), \
         patch("services.redis_lock.release_lock", new=AsyncMock()):
        reply = await appointment_agent.handle_appointment_message(db, store, customer, "oui", wa)
    assert "réservé" in reply
