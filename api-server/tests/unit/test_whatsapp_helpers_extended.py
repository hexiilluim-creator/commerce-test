"""Tests ciblés des garde-fous WhatsApp v24."""
from types import SimpleNamespace

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.v1 import whatsapp as mod


def test_build_canonical_payload_normalizes_message_fields():
    payload = mod._build_canonical_payload(msg={"id": "m1", "from": "2161", "type": "text", "text": {"body": "Bonjour"}}, store_id=7, phone_number_id="p1")
    assert payload["message_id"] == "m1"
    assert payload["id"] == "m1"
    assert payload["from_phone"] == "2161"
    assert payload["message_type"] == "text"
    assert payload["raw_message"]["text"]["body"] == "Bonjour"


@pytest.mark.asyncio
async def test_duplicate_detection_fail_open_without_redis(monkeypatch):
    monkeypatch.setattr(mod, "_get_async_redis", lambda: None)
    assert await mod._is_duplicate_wa_message("m1", 7) is False
    assert await mod._is_duplicate_wa_message("", 7) is False


@pytest.mark.asyncio
async def test_duplicate_detection_uses_set_nx_and_handles_existing_key(monkeypatch):
    class Redis:
        def __init__(self, response): self.response = response; self.calls = []
        async def set(self, *args, **kwargs): self.calls.append((args, kwargs)); return self.response
    first = Redis(True)
    async def first_client(): return first
    monkeypatch.setattr(mod, "_get_async_redis", first_client)
    assert await mod._is_duplicate_wa_message("m1", 7) is False
    assert first.calls[0][0][0] == "omnicall:wa:dedup:7:m1"
    assert first.calls[0][1] == {"nx": True, "ex": 86400}
    second = Redis(False)
    async def second_client(): return second
    monkeypatch.setattr(mod, "_get_async_redis", second_client)
    assert await mod._is_duplicate_wa_message("m1", 7) is True


@pytest.mark.asyncio
async def test_duplicate_detection_fails_open_on_redis_error(monkeypatch):
    async def broken():
        raise RuntimeError("redis down")
    monkeypatch.setattr(mod, "_get_async_redis", broken)
    assert await mod._is_duplicate_wa_message("m2", 7) is False


@pytest.mark.asyncio
async def test_plan_gate_rejects_missing_tenant_and_non_whatsapp_plan(monkeypatch):
    monkeypatch.setattr(mod, "_sid", lambda: None)
    with pytest.raises(HTTPException) as missing:
        await mod._require_whatsapp_plan()
    assert missing.value.status_code == 401

    monkeypatch.setattr(mod, "_sid", lambda: 7)
    class Snapshot:
        plan_code = "starter"
        def has_feature(self, feature): return False
    async def snapshot(_): return Snapshot()
    monkeypatch.setattr("security_overlay.billing_overlay.get_billing_snapshot", snapshot)
    with pytest.raises(HTTPException) as forbidden:
        await mod._require_whatsapp_plan()
    assert forbidden.value.status_code == 403
    assert forbidden.value.detail["required_plan"] == "pro_whatsapp"


@pytest.mark.asyncio
async def test_plan_gate_accepts_feature(monkeypatch):
    monkeypatch.setattr(mod, "_sid", lambda: 7)
    class Snapshot:
        plan_code = "pro_whatsapp"
        def has_feature(self, feature): return feature == "channels.whatsapp"
    async def snapshot(_): return Snapshot()
    monkeypatch.setattr("security_overlay.billing_overlay.get_billing_snapshot", snapshot)
    assert await mod._require_whatsapp_plan() is None


@pytest.mark.asyncio
async def test_verify_webhook_echoes_arbitrary_challenge_and_rejects_invalid(monkeypatch):
    monkeypatch.setattr(mod.settings, "WHATSAPP_VERIFY_TOKEN", "verify-secret")
    response = await mod.verify_webhook("subscribe", "abc-123", "verify-secret")
    assert response.status_code == 200
    assert response.body == b"abc-123"
    with pytest.raises(HTTPException) as exc:
        await mod.verify_webhook("subscribe", "abc", "wrong")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_register_phone_creates_and_updates_mapping(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    monkeypatch.setattr(mod, "_sid", lambda: 7)
    db = AsyncMock(); db.add = MagicMock()
    empty = MagicMock(); empty.scalar_one_or_none.return_value = None; db.execute.return_value = empty
    created = await mod.register_phone(mod.RegisterPhoneRequest(phone_number_id="p1", display_phone="+216"), db)
    assert created["store_id"] == 7 and created["status"] == "registered"
    existing = SimpleNamespace(phone_number_id="p1", store_id=7, display_phone=None, is_active=False)
    found = MagicMock(); found.scalar_one_or_none.return_value = existing; db.execute.return_value = found
    updated = await mod.register_phone(mod.RegisterPhoneRequest(phone_number_id="p1", display_phone="+217"), db)
    assert updated["display_phone"] == "+217" and existing.is_active is True


@pytest.mark.asyncio
async def test_register_phone_rejects_mapping_owned_by_other_store(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    monkeypatch.setattr(mod, "_sid", lambda: 7)
    db = AsyncMock(); found = MagicMock(); found.scalar_one_or_none.return_value = SimpleNamespace(store_id=9, phone_number_id="p1"); db.execute.return_value = found
    with pytest.raises(HTTPException) as exc:
        await mod.register_phone(mod.RegisterPhoneRequest(phone_number_id="p1"), db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_owner_phone_set_remove_and_missing_store(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    monkeypatch.setattr(mod, "_sid", lambda: 7)
    db = AsyncMock(); store = SimpleNamespace(owner_phone=None); found = MagicMock(); found.scalar_one_or_none.return_value = store; db.execute.return_value = found
    result = await mod.set_owner_phone(mod.SetOwnerPhoneRequest(owner_phone="+216123"), db)
    assert result["ok"] and store.owner_phone == "+216123"
    removed = await mod.remove_owner_phone(db)
    assert removed["ok"] and store.owner_phone is None
    missing = MagicMock(); missing.scalar_one_or_none.return_value = None; db.execute.return_value = missing
    with pytest.raises(HTTPException) as exc:
        await mod.set_owner_phone(mod.SetOwnerPhoneRequest(owner_phone="+216123"), db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_mute_store_delegates_and_requires_tenant(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(mod, "_sid", lambda: 7)
    mute = AsyncMock(return_value={"muted": True, "minutes": 30})
    monkeypatch.setattr("services.agent_mute.mute_store", mute)
    result = await mod.mute_store_agent(mod.MuteRequest(minutes=30), AsyncMock())
    assert result["muted"] is True and mute.await_args.args == (7,)
    monkeypatch.setattr(mod, "_sid", lambda: None)
    with pytest.raises(HTTPException) as exc:
        await mod.mute_store_agent(mod.MuteRequest(), AsyncMock())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_receive_webhook_rejects_missing_and_invalid_signature(monkeypatch):
    class Req:
        headers = {}
        async def body(self): return b'{}'
    with pytest.raises(HTTPException) as missing:
        await mod.receive_webhook(Req(), SimpleNamespace(add_task=lambda *a, **k: None), AsyncMock())
    assert missing.value.status_code == 401
    monkeypatch.setattr(mod.settings, "WHATSAPP_APP_SECRET", "secret")
    Req.headers = {"X-Hub-Signature-256": "sha256=bad"}
    with pytest.raises(HTTPException) as invalid:
        await mod.receive_webhook(Req(), SimpleNamespace(add_task=lambda *a, **k: None), AsyncMock())
    assert invalid.value.status_code == 401


@pytest.mark.asyncio
async def test_receive_webhook_routes_message_types_to_v8_without_external_execution(monkeypatch):
    import hashlib, hmac
    from unittest.mock import AsyncMock, MagicMock, patch
    class Req:
        def __init__(self, raw, headers): self._raw = raw; self.headers = headers
        async def body(self): return self._raw
    monkeypatch.setattr(mod.settings, "WHATSAPP_APP_SECRET", "secret")
    messages = [
        {"id": "m-text", "from": "2161", "type": "text", "text": {"body": "Bonjour"}},
        {"id": "m-image", "from": "2161", "type": "image", "image": {"id": "media-1", "mime_type": "image/jpeg"}},
        {"id": "m-button", "from": "2161", "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "confirm", "title": "Commander"}}},
        {"id": "m-location", "from": "2161", "type": "location", "location": {"latitude": 36.8, "longitude": 10.1}},
        {"id": "m-sticker", "from": "2161", "type": "sticker", "sticker": {"id": "s1"}},
    ]
    raw = json.dumps({"entry": [{"changes": [{"field": "messages", "value": {"metadata": {"phone_number_id": "phone-1"}, "messages": messages, "statuses": []}}]}]}).encode()
    sig = hmac.new(b"secret", raw, hashlib.sha256).hexdigest()
    bg = SimpleNamespace(tasks=[], add_task=lambda *args, **kwargs: bg.tasks.append((args, kwargs)))
    decision = SimpleNamespace(active=False)
    with patch.object(mod, "_resolve_store_id", new=AsyncMock(return_value=7)), patch.object(mod, "_is_duplicate_wa_message", new=AsyncMock(return_value=False)), patch("services.agent_mute.should_ai_respond", new=AsyncMock(return_value=(True, None))), patch.object(mod, "get_active_route_decision", return_value=decision), patch.object(mod.process_whatsapp_message, "delay") as delay, patch.object(mod._metrics.webhook_events_total, "labels", return_value=MagicMock()), patch.object(mod, "_push_to_stream", new=AsyncMock()), patch.object(mod, "_shadow_v9_task"):
        result = await mod.receive_webhook(Req(raw, {"X-Hub-Signature-256": "sha256=" + sig}), bg, AsyncMock())
    assert result == {"status": "received"}
    assert delay.call_count == 4
    assert any(call.kwargs.get("message_text") == "Bonjour" for call in delay.call_args_list)
    assert len(bg.tasks) >= 4


@pytest.mark.asyncio
async def test_agent_controls_delegate_and_require_tenant(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(mod, "_sid", lambda: 7)
    unmute = AsyncMock(return_value={"muted": False}); takeover = AsyncMock(return_value={"taken_over": True}); release = AsyncMock(return_value={"released": True}); status = AsyncMock(return_value={"ai_mode": "partial"})
    monkeypatch.setattr("services.agent_mute.unmute_store", unmute); monkeypatch.setattr("services.agent_mute.takeover_customer", takeover); monkeypatch.setattr("services.agent_mute.release_customer", release); monkeypatch.setattr("services.agent_mute.get_store_agent_status", status)
    assert (await mod.unmute_store_agent(AsyncMock()))["muted"] is False
    assert (await mod.takeover_customer_agent("216", mod.TakeoverRequest(minutes=10), AsyncMock()))["taken_over"] is True
    assert (await mod.release_customer_agent("216", AsyncMock()))["released"] is True
    assert (await mod.get_agent_status(AsyncMock()))["ai_mode"] == "partial"
    monkeypatch.setattr(mod, "_sid", lambda: None)
    with pytest.raises(HTTPException): await mod.get_agent_status(AsyncMock())


@pytest.mark.asyncio
async def test_opt_out_creates_unknown_customer_and_updates_existing():
    from unittest.mock import AsyncMock, MagicMock
    db = AsyncMock(); db.add = MagicMock(); missing = MagicMock(); missing.scalar_one_or_none.return_value = None; db.execute.return_value = missing
    created = await mod.opt_out(mod.OptOutRequest(from_phone="2161", store_id=7), db)
    assert created == {"status": "opted_out", "created": True} and db.add.called
    existing_customer = SimpleNamespace(opted_out=False, opted_out_at=None)
    found = MagicMock(); found.scalar_one_or_none.return_value = existing_customer; db.execute.return_value = found
    updated = await mod.opt_out(mod.OptOutRequest(from_phone="2161", store_id=7), db)
    assert updated["created"] is False and existing_customer.opted_out is True
    existing_customer.opted_out = True
    same = await mod.opt_out(mod.OptOutRequest(from_phone="2161", store_id=7), db)
    assert same["status"] == "opted_out"
