from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "development")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key_at_least_32_chars_long_for_safety")
os.environ.setdefault("ENCRYPTION_KEY", "mY6rHQ0TLMlAuHCXKJHtEPeyLyvOyBK9p0KW1MLrnu8=")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key-not-real")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-chars-minimum-ok")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_wa_verify")
os.environ.setdefault("INSTAGRAM_VERIFY_TOKEN", "test_ig_verify")
os.environ.setdefault("FACEBOOK_VERIFY_TOKEN", "test_fb_verify")
os.environ.setdefault("TIKTOK_VERIFY_TOKEN", "test_tt_verify")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test_health_token")

from services.invoice_service import create_and_save_invoice, generate_invoice_number
from services.upload_security import UploadRejected, validate_upload


@pytest.mark.unit
def test_validate_upload_accepts_valid_jpeg() -> None:
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"test-jpeg-payload"
    detected = validate_upload(jpeg_bytes, "photo.jpg")
    assert detected == "image/jpeg"


@pytest.mark.unit
def test_validate_upload_rejects_exe_renamed_jpg() -> None:
    exe_bytes = b"MZ" + b"fake-executable"
    with pytest.raises(UploadRejected):
        validate_upload(exe_bytes, "virus.jpg")


@pytest.mark.unit
def test_validate_upload_rejects_over_10mb() -> None:
    huge_payload = b"\xff\xd8\xff" + (b"0" * (10 * 1024 * 1024))
    with pytest.raises(UploadRejected):
        validate_upload(huge_payload, "huge.jpg")


@pytest.mark.unit
def test_generate_invoice_number_is_unique() -> None:
    first = generate_invoice_number(12)
    second = generate_invoice_number(12)
    assert first != second
    assert first.startswith("INV-0012-")
    assert second.startswith("INV-0012-")


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    def __init__(self, order, store):
        self.order = order
        self.store = store
        self.calls = 0

    async def execute(self, statement):
        self.calls += 1
        if self.calls == 1:
            return _FakeScalarResult(self.order)
        return _FakeScalarResult(self.store)


@pytest.mark.asyncio
async def test_create_and_save_invoice_returns_non_empty_pdf() -> None:
    store = SimpleNamespace(id=7, name="AutoCommerce Store")
    order = SimpleNamespace(
        id=55,
        store_id=7,
        total_amount=119.0,
        items=[
            {"name": "Filtre à huile", "qty": 2, "unit_price": 15.0},
            {"name": "Plaquettes de frein", "qty": 1, "unit_price": 50.0},
        ],
        store=None,
    )
    db = _FakeDB(order=order, store=store)

    result = await create_and_save_invoice(store_id=7, order_id=55, db=db)

    assert result["status"] == "generated"
    assert result["invoice_number"].startswith("INV-0007-")
    assert isinstance(result["pdf_bytes"], bytes | bytearray)
    assert len(result["pdf_bytes"]) > 100
    assert result["pdf_bytes"].startswith(b"%PDF")
