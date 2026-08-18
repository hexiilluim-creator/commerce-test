from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.email_queue import QueueResult
from services.email_sender import EmailDeliveryError
from services.email_service import send_invoice_email


@pytest.mark.asyncio
async def test_send_success():
    with patch("services.email_service._get_queue") as get_queue:
        get_queue.return_value.enqueue = AsyncMock(return_value=QueueResult(status="sent", attempts=1))
        await send_invoice_email("user@example.com", "https://example.com/invoice.pdf", "A-1")


@pytest.mark.asyncio
async def test_smtp_unavailable_no_silent_drop():
    with patch("services.email_service._get_queue") as get_queue:
        get_queue.return_value.enqueue = AsyncMock(return_value=QueueResult(status="DLQ", attempts=3, last_error="SMTP down"))
        with pytest.raises(EmailDeliveryError):
            await send_invoice_email("user@example.com", "https://example.com/invoice.pdf", "A-1")


@pytest.mark.asyncio
async def test_retry_then_dlq():
    with patch("services.email_service._get_queue") as get_queue:
        mocked = AsyncMock(return_value=QueueResult(status="DLQ", attempts=3, last_error="boom"))
        get_queue.return_value.enqueue = mocked
        with pytest.raises(EmailDeliveryError):
            await send_invoice_email("user@example.com", "https://example.com/invoice.pdf", "A-1")
        assert mocked.await_count == 1
