from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.v1.settings import (
    InviteUserRequest,
    PaymentProviderConfig,
    StoreSettingsUpdate,
    UpdateUserRoleRequest,
    _serialize_store,
    _serialize_user,
)


def test_settings_schemas_validate_and_normalize_inputs():
    data = StoreSettingsUpdate(country=" tn ", default_tax_country="fr", currency=" eur ")
    assert data.country == "TN" and data.default_tax_country == "FR" and data.currency == "EUR"
    assert PaymentProviderConfig(provider="cash").enabled is True
    assert UpdateUserRoleRequest(role="viewer").role == "viewer"
    with pytest.raises(ValidationError):
        StoreSettingsUpdate(country="TUN", currency="XYZ")
    with pytest.raises(ValidationError):
        InviteUserRequest(email="not-email", password="pw")


def test_settings_serializers_mask_and_format_orm_objects():
    store = SimpleNamespace(id=3, name="Demo", slug="demo", language="fr", timezone="Africa/Tunis", country="TN", currency="TND", logo_url=None, support_email="a@b.test", description="Shop", address=None, phone_display=None, website_url=None, category=None, opening_hours=None, services=None, latitude=None, longitude=None, social_links=None, ai_agent_prompt=None, order_confirmation_msg=None, post_payment_msg=None, conversation_timeout_min=None, stock_api_url=None, whatsapp_phone=None, whatsapp_phone_number_id=None, whatsapp_business_account_id=None, whatsapp_configured=False, is_active=True, created_at=datetime(2026, 8, 1, tzinfo=UTC))
    result = _serialize_store(store)
    assert result["id"] == 3 and result["currency"] == "TND"
    user = SimpleNamespace(id=4, email="u@b.test", role="viewer", is_active=True, created_at=datetime(2026, 8, 14, tzinfo=UTC))
    user_result = _serialize_user(user)
    assert user_result["email"] == "u@b.test" and user_result["role"] == "viewer"



def test_settings_credentials_and_role_schemas_reject_invalid_values():
    from api.v1.settings import WhatsAppCredentialsUpdate
    assert WhatsAppCredentialsUpdate(access_token="wa-token", phone_number_id="phone-1").phone_number_id == "phone-1"
    assert InviteUserRequest(email="user@gmail.com", password="strong-password", role="admin").role == "admin"
    assert UpdateUserRoleRequest(role="admin").role == "admin"
    assert WhatsAppCredentialsUpdate(access_token="", phone_number_id="phone-1").access_token == ""
    assert InviteUserRequest(email="user@gmail.com", password="", role="viewer").password == ""


def test_settings_update_accepts_public_store_fields_and_rejects_bad_currency():
    data = StoreSettingsUpdate(
        name="Garage", language="fr", timezone="Africa/Tunis", description="Auto parts",
        opening_hours={"mon": "08:00-17:00"}, services=["delivery"], latitude=36.8,
        longitude=10.1, social_links={"facebook": "https://facebook.test/page"},
        conversation_timeout_min=30, stock_api_url="https://stock.example.test/api",
    )
    assert data.name == "Garage" and data.services == ["delivery"]
    with pytest.raises(ValidationError):
        StoreSettingsUpdate(currency="XXX")


def test_payment_provider_config_preserves_security_flags():
    cfg = PaymentProviderConfig(provider="stripe", api_key="enc-api", secret_key="enc-secret", sandbox=True, enabled=False)
    assert cfg.provider == "stripe" and cfg.sandbox is True and cfg.enabled is False


@pytest.mark.asyncio
async def test_payment_settings_mask_encrypt_and_remove_provider():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock()
    store = SimpleNamespace(id=3, payment_config={"cash": {"api_key": "abcd1234", "secret_key": "secret9999", "enabled": True}})
    result = MagicMock(); result.scalar_one_or_none.return_value = store
    db.execute.return_value = result
    with patch.object(module, "_sid", return_value=3):
        masked = await module.get_payment_config(db)
    assert masked["configured"] == ["cash"] and masked["providers"]["cash"]["api_key"] == "****1234"
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=3), patch.object(type(module.app_settings), "encrypt", side_effect=lambda value, context=None: f"ENC({value})"), patch.object(module, "_audit", new=AsyncMock()):
            configured = await module.set_payment_config(module.PaymentProviderConfig(provider="flouci", api_key="key", secret_key="secret", sandbox=True), SimpleNamespace(), db)
            assert configured["status"] == "configured" and store.payment_config["flouci"]["api_key"] == "enc_ENC(key)"
            removed = await module.remove_payment_config("cash", SimpleNamespace(), db)
    finally:
        module.current_user_role.reset(token)
    assert removed["status"] == "removed" and "cash" not in store.payment_config


@pytest.mark.asyncio
async def test_payment_settings_rejects_unknown_provider_and_missing_tenant():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock()
    store = SimpleNamespace(id=3, payment_config={})
    result = MagicMock(); result.scalar_one_or_none.return_value = store
    db.execute.return_value = result
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=3):
            with pytest.raises(HTTPException) as exc:
                await module.remove_payment_config("missing", SimpleNamespace(), db)
        assert exc.value.status_code == 404
        with patch.object(module, "_sid", return_value=None):
            with pytest.raises(HTTPException) as no_tenant:
                await module.get_payment_config(db)
    finally:
        module.current_user_role.reset(token)
    assert no_tenant.value.status_code == 401


@pytest.mark.asyncio
async def test_whatsapp_credentials_encrypt_store_and_remove():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock(); store = SimpleNamespace(id=3, whatsapp_access_token_enc=None, whatsapp_phone_number_id=None)
    result = MagicMock(); result.scalar_one_or_none.return_value = store
    db.execute.return_value = result
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=3), patch.object(type(module.app_settings), "encrypt", side_effect=lambda value, context=None: f"ENC({value})"), patch.object(module, "_audit", new=AsyncMock()):
            configured = await module.set_whatsapp_credentials(module.WhatsAppCredentialsUpdate(access_token="token", phone_number_id="phone"), SimpleNamespace(), db)
            encrypted_value = store.whatsapp_access_token_enc
            removed = await module.remove_whatsapp_credentials(SimpleNamespace(), db)
    finally:
        module.current_user_role.reset(token)
    assert configured["token_stored"] is True and encrypted_value == "ENC(token)"
    assert removed["fallback"] == "global_settings" and store.whatsapp_phone_number_id is None


@pytest.mark.asyncio
async def test_audit_log_serializes_entries_and_requires_tenant():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock()
    log = SimpleNamespace(id=1, action="store.update", resource_type="store", resource_id="3", detail={"country": "TN"}, ip_address="127.0.0.1", created_at=datetime(2026, 8, 14, tzinfo=UTC))
    result = MagicMock(); result.scalars.return_value.all.return_value = [log]
    db.execute.return_value = result
    with patch.object(module, "_sid", return_value=3):
        entries = await module.get_audit_log(limit=10, db=db)
    assert entries[0]["action"] == "store.update" and entries[0]["created_at"].startswith("2026-08-14")
    with patch.object(module, "_sid", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await module.get_audit_log(db=db)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_team_management_lists_invites_updates_and_revokes_users():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock(); db.add = MagicMock(); store_id = 3
    active = SimpleNamespace(id=4, email="active@example.com", role="viewer", is_active=True, created_at=datetime(2026, 8, 14, tzinfo=UTC))
    list_result = MagicMock(); list_result.scalars.return_value.all.return_value = [active]
    db.execute.return_value = list_result
    admin = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=store_id):
            listed = await module.list_users(db)
        assert listed[0]["email"] == "active@example.com"
        existing_result = MagicMock(); existing_result.scalar_one_or_none.return_value = None
        db.execute.return_value = existing_result
        with patch.object(module, "_sid", return_value=store_id), patch.object(module, "_audit", new=AsyncMock()), patch.object(module, "hash_password", return_value="HASH"), patch.object(module, "get_subscription_overview", new=AsyncMock(return_value={"max_users": 3})):
            db.execute.side_effect = [existing_result, MagicMock(scalar_one=lambda: 1)]
            invited = await module.invite_user(module.InviteUserRequest(email="new@example.com", password="secret", role="viewer"), SimpleNamespace(), db)
        assert invited["email"] == "new@example.com" and invited["role"] == "viewer"
        updated = SimpleNamespace(id=4, email="active@example.com", role="viewer", is_active=True, created_at=active.created_at)
        user_result = MagicMock(); user_result.scalar_one_or_none.return_value = updated
        db.execute.side_effect = None
        db.execute.return_value = user_result
        with patch.object(module, "_sid", return_value=store_id), patch.object(module, "_audit", new=AsyncMock()):
            role_result = await module.update_user_role(4, module.UpdateUserRoleRequest(role="admin"), SimpleNamespace(), db)
            await module.revoke_user(4, SimpleNamespace(), db)
    finally:
        module.current_user_role.reset(admin)
    assert role_result["role"] == "admin" and updated.is_active is False


@pytest.mark.asyncio
async def test_team_management_rejects_duplicate_invite_and_non_admin_access():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock(); duplicate = MagicMock(); duplicate.scalar_one_or_none.return_value = SimpleNamespace(id=8)
    db.execute.return_value = duplicate
    admin = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=3):
            with pytest.raises(HTTPException) as duplicate_exc:
                await module.invite_user(module.InviteUserRequest(email="used@example.com", password="secret"), SimpleNamespace(), db)
    finally:
        module.current_user_role.reset(admin)
    assert duplicate_exc.value.status_code == 409
    viewer = module.current_user_role.set("viewer")
    try:
        with patch.object(module, "_sid", return_value=3):
            with pytest.raises(HTTPException) as access_exc:
                await module.invite_user(module.InviteUserRequest(email="new@example.com", password="secret"), SimpleNamespace(), db)
    finally:
        module.current_user_role.reset(viewer)
    assert access_exc.value.status_code == 403


@pytest.mark.asyncio
async def test_team_management_enforces_active_user_quota():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module

    db = AsyncMock()
    duplicate = MagicMock(); duplicate.scalar_one_or_none.return_value = None
    count = MagicMock(); count.scalar_one.return_value = 1
    db.execute.side_effect = [duplicate, count]
    admin = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=3), patch.object(module, "get_subscription_overview", new=AsyncMock(return_value={"max_users": 1})):
            with pytest.raises(HTTPException) as exc:
                await module.invite_user(module.InviteUserRequest(email="blocked@example.com", password="secret"), SimpleNamespace(), db)
    finally:
        module.current_user_role.reset(admin)
    assert exc.value.status_code == 403
    assert "User limit reached" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_stock_source_dashboard_and_ssrf_validation():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock(); store = SimpleNamespace(id=3, stock_source_type=None, stock_source_config_enc=None)
    store_result = MagicMock(); store_result.scalar_one_or_none.return_value = store
    count_result = MagicMock(); count_result.scalar.return_value = 12
    db.execute.side_effect = [store_result, store_result, count_result, store_result]
    admin = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=3), patch.object(type(module.app_settings), "encrypt", side_effect=lambda value, context=None: "ENC"), patch.object(module, "_audit", new=AsyncMock()):
            saved = await module.set_stock_source(module.StockSourceConfig(source_type="dashboard", config={"x": "y"}), SimpleNamespace(), db)
            checked = await module.test_stock_source(module.StockSourceConfig(source_type="dashboard"), db)
    finally:
        module.current_user_role.reset(admin)
    assert saved["source_type"] == "dashboard" and checked["count"] == 12
    admin2 = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=3):
            with pytest.raises(HTTPException) as ssrf:
                await module.test_stock_source(module.StockSourceConfig(source_type="google_sheets", config={"sheet_url": "https://evil.example/sheet"}), db)
    finally:
        module.current_user_role.reset(admin2)
    assert ssrf.value.status_code == 400


@pytest.mark.asyncio
async def test_oem_config_masks_keys_and_updates_mode():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock(); store = SimpleNamespace(id=3, auto_parts_mode=False, nhtsa_enabled=True, tecdoc_api_key_enc=None, tecdoc_provider_id=None, autoiso_api_key_enc=None, stock_source_type="dashboard")
    result = MagicMock(); result.scalar_one_or_none.return_value = store
    db.execute.return_value = result
    admin = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=3), patch.object(type(module.app_settings), "encrypt", side_effect=lambda value, context=None: f"ENC({value})"), patch.object(module, "_audit", new=AsyncMock()):
            updated = await module.set_oem_config(module.OemApiConfig(tecdoc_api_key="td", tecdoc_provider_id="p1", autoiso_api_key="ai", auto_parts_mode=True, nhtsa_enabled=False), SimpleNamespace(), db)
        with patch.object(module, "_sid", return_value=3):
            readback = await module.get_oem_config(db)
    finally:
        module.current_user_role.reset(admin)
    assert updated["auto_parts_mode"] is True and readback["tecdoc_configured"] is True and readback["autoiso_configured"] is True


@pytest.mark.asyncio
async def test_store_completeness_reports_missing_fields_and_online_state():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock()
    incomplete = SimpleNamespace(id=3, name="Demo", slug="demo", whatsapp_phone=None, language="fr", logo_url=None, description=None, support_email=None, ai_agent_prompt=None, whatsapp_access_token_enc=None, whatsapp_phone_number_id=None)
    store_result = MagicMock(); store_result.scalar_one_or_none.return_value = incomplete
    count_result = MagicMock(); count_result.scalar.return_value = 0
    db.execute.side_effect = [store_result, count_result]
    with patch.object(module, "_sid", return_value=3):
        result = await module.get_store_completeness(db)
    assert result["is_online"] is False and result["score"] == 40 and result["product_count"] == 0
    assert any(item["key"] == "whatsapp_phone" for item in result["required_missing"])
    complete = SimpleNamespace(id=3, name="Demo", slug="demo", whatsapp_phone="+216", language="fr", logo_url="logo", description="Shop", support_email="a@example.com", ai_agent_prompt="Hello", whatsapp_access_token_enc="ENC", whatsapp_phone_number_id="phone")
    store_result.scalar_one_or_none.return_value = complete; count_result.scalar.return_value = 4
    db.execute.side_effect = [store_result, count_result]
    with patch.object(module, "_sid", return_value=3):
        online = await module.get_store_completeness(db)
    assert online["is_online"] is True and online["score"] == 100 and online["public_url"] == "/store/demo"


@pytest.mark.asyncio
async def test_stock_source_google_sheets_requires_canonical_url():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock(); result = MagicMock(); result.scalar_one_or_none.return_value = SimpleNamespace(id=3); db.execute.return_value = result
    admin = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=3):
            with pytest.raises(HTTPException) as exc:
                await module.test_stock_source(module.StockSourceConfig(source_type="google_sheets", config={"sheet_url": "https://example.com/file"}), db)
    finally:
        module.current_user_role.reset(admin)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_stock_source_shop_integrations_reject_private_and_missing_credentials():
    from unittest.mock import AsyncMock, MagicMock, patch
    import api.v1.settings as module
    db = AsyncMock(); result = MagicMock(); result.scalar_one_or_none.return_value = SimpleNamespace(id=3); db.execute.return_value = result
    admin = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_sid", return_value=3):
            with pytest.raises(HTTPException) as private_exc:
                await module.test_stock_source(module.StockSourceConfig(source_type="woocommerce", config={"site_url": "http://127.0.0.1"}), db)
            with pytest.raises(HTTPException) as wc_exc:
                await module.test_stock_source(module.StockSourceConfig(source_type="woocommerce", config={"site_url": "https://shop.example"}), db)
            with pytest.raises(HTTPException) as ps_exc:
                await module.test_stock_source(module.StockSourceConfig(source_type="prestashop", config={"site_url": "https://shop.example"}), db)
    finally:
        module.current_user_role.reset(admin)
    assert private_exc.value.status_code == 400 and wc_exc.value.status_code == 400 and ps_exc.value.status_code == 400
