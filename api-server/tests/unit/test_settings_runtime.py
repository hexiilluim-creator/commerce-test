from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from fastapi import HTTPException

from api.v1.settings import (
    InviteUserRequest,
    PaymentProviderConfig,
    StoreSettingsUpdate,
    _serialize_store,
    _serialize_user,
    get_payment_config,
    set_payment_config,
)


def test_settings_validators_normalize_and_reject():
    body = StoreSettingsUpdate(country=" tn ", currency=" eur ")
    assert body.country == "TN"
    assert body.currency == "EUR"
    with pytest.raises(ValidationError):
        StoreSettingsUpdate(country="TUN")
    with pytest.raises(ValidationError):
        StoreSettingsUpdate(currency="XXX")


def test_settings_schemas_validate_email_and_provider():
    assert InviteUserRequest(email="admin@example.com", password="safe-password", role="admin").role == "admin"
    assert PaymentProviderConfig(provider="stripe", sandbox=True).enabled is True
    with pytest.raises(ValidationError):
        InviteUserRequest(email="bad", password="x")


def test_serializers_never_expose_secrets():
    now = datetime.now(timezone.utc)
    store = SimpleNamespace(
        id=1, name="Demo", slug="demo", language="fr", timezone="Africa/Tunis", country="TN", currency=None,
        default_tax_country=None, logo_url=None, support_email=None, ai_agent_prompt="x",
        order_confirmation_msg=None, post_payment_msg=None, conversation_timeout_min=30, stock_api_url=None,
        whatsapp_phone="216", whatsapp_access_token_enc="encrypted", whatsapp_phone_number_id="pid",
        is_active=True, created_at=now, description=None, address=None, phone_display=None,
        website_url=None, category=None, opening_hours=None, services=None, latitude=None,
        longitude=None, social_links=None,
    )
    data = _serialize_store(store)
    assert data["currency"] == "TND"
    assert data["whatsapp_configured"] is True
    assert "whatsapp_access_token_enc" not in data
    user = _serialize_user(SimpleNamespace(id=2, email="x@y.com", role="viewer", is_active=True, created_at=now))
    assert user["email"] == "x@y.com"


@pytest.mark.asyncio
async def test_get_payment_config_masks_keys():
    db = AsyncMock()
    store = SimpleNamespace(payment_config={"stripe": {"api_key": "sk_live_1234", "secret_key": "sec9999", "enabled": True}})
    result = MagicMock()
    result.scalar_one_or_none.return_value = store
    db.execute.return_value = result
    with patch("api.v1.settings._sid", return_value=4):
        data = await get_payment_config(db)
    assert data["configured"] == ["stripe"]
    assert data["providers"]["stripe"]["api_key"] == "****1234"
    assert data["providers"]["stripe"]["secret_key"] == "****9999"


@pytest.mark.asyncio
async def test_set_payment_config_encrypts_and_audits():
    db = AsyncMock()
    store = SimpleNamespace(payment_config={})
    result = MagicMock()
    result.scalar_one_or_none.return_value = store
    db.execute.return_value = result
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    body = PaymentProviderConfig(provider="flouci", api_key="key", secret_key="secret", sandbox=True)
    import api.v1.settings as settings_module
    role_token = settings_module.current_user_role.set("admin")
    try:
        with patch("api.v1.settings._sid", return_value=4), \
             patch("api.v1.settings.app_settings", SimpleNamespace(encrypt=lambda v: f"cipher-{v}")), \
             patch("api.v1.settings._audit", new=AsyncMock()):
            data = await set_payment_config(body, request, db)
    finally:
        settings_module.current_user_role.reset(role_token)
    assert data["status"] == "configured"
    assert store.payment_config["flouci"]["api_key"] == "enc_cipher-key"
    assert store.payment_config["flouci"]["secret_key"] == "enc_cipher-secret"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_payment_config_success_and_missing_provider():
    from api.v1.settings import remove_payment_config
    db = AsyncMock(); store = SimpleNamespace(payment_config={"cash": {"enabled": True}})
    result = MagicMock(); result.scalar_one_or_none.return_value = store; db.execute.return_value = result
    request = SimpleNamespace(client=None)
    import api.v1.settings as settings_module
    token = settings_module.current_user_role.set("admin")
    try:
        with patch("api.v1.settings._sid", return_value=4), patch("api.v1.settings._audit", new=AsyncMock()):
            response = await remove_payment_config("cash", request, db)
            assert response["status"] == "removed"
            with pytest.raises(HTTPException, match="not configured"):
                await remove_payment_config("cash", request, db)
    finally:
        settings_module.current_user_role.reset(token)


def test_require_admin_rejects_viewer():
    from api.v1.settings import _require_admin
    import api.v1.settings as settings_module
    token = settings_module.current_user_role.set("viewer")
    try:
        with pytest.raises(HTTPException) as exc:
            _require_admin()
        assert exc.value.status_code == 403
    finally:
        settings_module.current_user_role.reset(token)


@pytest.mark.asyncio
async def test_user_management_list_update_and_revoke():
    from api.v1.settings import list_users, update_user_role, revoke_user, UpdateUserRoleRequest
    db = AsyncMock(); user = SimpleNamespace(id=8, email="u@x.com", role="viewer", is_active=True, created_at=None, store_id=4)
    result = MagicMock(); result.scalars.return_value.all.return_value = [user]; result.scalar_one_or_none.return_value = user; db.execute.return_value = result
    import api.v1.settings as settings_module
    token = settings_module.current_user_role.set("admin")
    try:
        with patch("api.v1.settings._sid", return_value=4), patch("api.v1.settings._audit", new=AsyncMock()):
            assert (await list_users(db))[0]["email"] == "u@x.com"
            changed = await update_user_role(8, UpdateUserRoleRequest(role="admin"), SimpleNamespace(client=None), db)
            assert changed["role"] == "admin"
            await revoke_user(8, SimpleNamespace(client=None), db)
    finally:
        settings_module.current_user_role.reset(token)
    assert user.is_active is False


@pytest.mark.asyncio
async def test_whatsapp_credentials_set_and_remove():
    from api.v1.settings import set_whatsapp_credentials, remove_whatsapp_credentials, WhatsAppCredentialsUpdate
    db = AsyncMock(); store = SimpleNamespace(whatsapp_access_token_enc=None, whatsapp_phone_number_id=None)
    result = MagicMock(); result.scalar_one_or_none.return_value = store; db.execute.return_value = result
    import api.v1.settings as settings_module
    token = settings_module.current_user_role.set("admin")
    try:
        with patch("api.v1.settings._sid", return_value=4), patch("api.v1.settings.app_settings", SimpleNamespace(encrypt=lambda x: "enc-" + x)), patch("api.v1.settings._audit", new=AsyncMock()):
            out = await set_whatsapp_credentials(WhatsAppCredentialsUpdate(access_token="tok", phone_number_id="pid"), SimpleNamespace(client=None), db)
            assert out["token_stored"] is True and store.whatsapp_access_token_enc == "enc-tok"
            out2 = await remove_whatsapp_credentials(SimpleNamespace(client=None), db)
            assert out2["fallback"] == "global_settings" and store.whatsapp_access_token_enc is None
    finally:
        settings_module.current_user_role.reset(token)


@pytest.mark.asyncio
async def test_public_store_returns_products_and_rejects_missing():
    from api.v1.settings import get_public_store
    product = SimpleNamespace(id=9, name="Car", description=None, price=10, image_url=None, stock_qty=2)
    store = SimpleNamespace(id=4, name="Demo", slug="demo", is_active=True, whatsapp_phone="+216", language="fr")
    store_result = MagicMock(); store_result.scalar_one_or_none.return_value = store
    products_result = MagicMock(); products_result.scalars.return_value.all.return_value = [product]
    db = AsyncMock(); db.execute.side_effect = [store_result, products_result]
    data = await get_public_store("demo", db)
    assert data["slug"] == "demo" and data["product_count"] == 1
    assert data["products"][0]["price"] == 10.0
    missing = MagicMock(); missing.scalar_one_or_none.return_value = None
    db.execute.side_effect = [missing]
    with pytest.raises(HTTPException) as exc:
        await get_public_store("missing", db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_gdpr_export_serializes_tenant_data():
    from api.v1.settings import export_gdpr_data
    now = datetime.now(timezone.utc)
    store = SimpleNamespace(id=4, name="Demo", slug="demo", whatsapp_phone="+216", created_at=now, language="fr")
    product = SimpleNamespace(id=1, name="P", price=12, stock_qty=3, is_active=True)
    customer = SimpleNamespace(id=2, name="Client", whatsapp_phone="+2161", channel="whatsapp", opted_out=False, created_at=now)
    order = SimpleNamespace(id=3, status="paid", total_amount=15, created_at=now)
    user = SimpleNamespace(id=4, email="admin@example.com", role="admin", is_active=True)
    def result_scalar(value):
        r = MagicMock(); r.scalar_one_or_none.return_value = value; return r
    def result_all(values):
        r = MagicMock(); r.scalars.return_value.all.return_value = values; return r
    conv = MagicMock(); conv.scalar.return_value = 2
    db = AsyncMock(); db.execute.side_effect = [result_scalar(store), result_all([product]), result_all([customer]), result_all([order]), result_all([user]), conv]
    with patch("api.v1.settings._sid", return_value=4):
        data = await export_gdpr_data(SimpleNamespace(), db)
    assert data["users"]["count"] == 1
    assert data["customers"]["data"][0]["name"] == "Client"
    assert data["orders"]["data"][0]["total"] == "15"
    assert data["conversations"]["count"] == 2


@pytest.mark.asyncio
async def test_whatsapp_full_config_get_and_update():
    from api.v1.settings import get_whatsapp_config, update_whatsapp_config, WhatsAppFullConfig
    store = SimpleNamespace(whatsapp_access_token_enc="encrypted-token", whatsapp_phone_number_id="pid", whatsapp_phone="+216", extra_config={})
    result = MagicMock(); result.scalar_one_or_none.return_value = store
    db = AsyncMock(); db.execute.return_value = result
    with patch("api.v1.settings._sid", return_value=4):
        data = await get_whatsapp_config(db)
    assert data["token_configured"] is True and data["phone_number_id"] == "pid"
    import api.v1.settings as settings_module
    token = settings_module.current_user_role.set("admin")
    try:
        body = WhatsAppFullConfig(access_token="new", phone_number_id="new-pid", whatsapp_phone="+217", verify_token="verify", welcome_message="Hi")
        with patch("api.v1.settings._sid", return_value=4), patch("api.v1.settings.app_settings", SimpleNamespace(encrypt=lambda x: "enc-" + x)), patch("api.v1.settings._audit", new=AsyncMock()):
            out = await update_whatsapp_config(body, SimpleNamespace(client=None), db)
    finally:
        settings_module.current_user_role.reset(token)
    assert out["status"] == "updated" and store.whatsapp_phone_number_id == "new-pid"
    assert store.extra_config["wa_welcome_message"] == "Hi"
