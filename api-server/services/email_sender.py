"""Low-level SMTP sender with retries, timeout and PII-safe logging."""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import settings
from services.observability import get_tracer

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EmailMessage:
    to: str
    subject: str
    html_body: str
    template: str = "generic"
    store_id: int | None = None


class EmailDeliveryError(RuntimeError):
    pass


class EmailSender:
    def __init__(self) -> None:
        self.host = settings.SMTP_HOST
        self.port = int(settings.SMTP_PORT)
        self.username = settings.SMTP_USERNAME
        self.password = settings.SMTP_PASSWORD
        self.from_addr = settings.SMTP_FROM or settings.SMTP_USERNAME or "noreply@autocommerce.ai"
        self.use_tls = bool(settings.SMTP_USE_TLS)

    @property
    def configured(self) -> bool:
        return bool(self.host)

    async def ping(self) -> bool:
        if not self.configured:
            return False
        try:
            await asyncio.wait_for(asyncio.to_thread(self._smtp_ping), timeout=10)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("smtp_ping_failed error=%s", type(exc).__name__)
            return False

    def _smtp_ping(self) -> None:
        context = ssl.create_default_context()
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            if self.use_tls:
                smtp.starttls(context=context)
            if self.username:
                smtp.login(self.username, self.password)
            smtp.noop()

    def _send_sync(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = message.subject
        msg["From"] = self.from_addr
        msg["To"] = message.to
        msg.attach(MIMEText(message.html_body, "html", "utf-8"))
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            if self.use_tls:
                smtp.starttls(context=context)
            if self.username:
                smtp.login(self.username, self.password)
            smtp.sendmail(self.from_addr, message.to, msg.as_string())

    async def send(self, message: EmailMessage) -> None:
        if not self.configured:
            raise EmailDeliveryError("SMTP non configuré")
        tracer = get_tracer("autocommerce.email")
        span = tracer.start_span("email.send") if tracer else None
        if span is not None:
            span.set_attribute("email.template", message.template)
            span.set_attribute("email.store_id", int(message.store_id or 0))
        backoffs = [1, 4, 16]
        last_exc: Exception | None = None
        for attempt, delay in enumerate(backoffs, start=1):
            try:
                await asyncio.wait_for(asyncio.to_thread(self._send_sync, message), timeout=10)
                if span is not None:
                    span.set_attribute("email.attempt", attempt)
                    span.end()
                logger.info("email_sent template=%s attempt=%s", message.template, attempt)
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("email_send_retry template=%s attempt=%s error=%s", message.template, attempt, type(exc).__name__)
                if span is not None:
                    span.set_attribute("email.error", type(exc).__name__)
                if attempt < len(backoffs):
                    await asyncio.sleep(delay)
        if span is not None:
            span.end()
        raise EmailDeliveryError(str(last_exc or "delivery_failed"))
