"""High-level transactional email helpers backed by EmailQueue."""
from __future__ import annotations

from services.email_queue import EmailQueue
from services.email_sender import EmailDeliveryError, EmailMessage, EmailSender

queue: EmailQueue | None = None


def _get_queue() -> EmailQueue:
    global queue
    if queue is None:
        queue = EmailQueue(EmailSender())
    return queue


async def _send_email(to: str, subject: str, html_body: str, *, template: str = "generic", store_id: int | None = None):
    result = await _get_queue().enqueue(EmailMessage(to=to, subject=subject, html_body=html_body, template=template, store_id=store_id))
    if result.status != "sent":
        raise EmailDeliveryError(result.last_error or "email en DLQ")
    return result


async def send_password_reset_email(to_email: str, reset_token: str, store_name: str = "AutoCommerce", *, store_id: int | None = None) -> None:
    import os

    frontend_url = os.getenv("FRONTEND_URL", "")
    reset_url = f"{frontend_url}/reset-password?token={reset_token}"
    subject = f"[{store_name}] Réinitialisation de votre mot de passe"
    html = f"""
    <p>Bonjour,</p>
    <p>Cliquez sur le lien ci-dessous pour réinitialiser votre mot de passe :</p>
    <p><a href=\"{reset_url}\">{reset_url}</a></p>
    <p>Si vous n'avez pas demandé cette réinitialisation, ignorez cet email.</p>
    <p>— L'équipe {store_name}</p>
    """
    await _send_email(to_email, subject, html, template="password_reset", store_id=store_id)


async def send_invoice_email(to_email: str, invoice_url: str, order_ref: str, store_name: str = "AutoCommerce", *, store_id: int | None = None) -> None:
    subject = f"[{store_name}] Votre facture #{order_ref}"
    html = f"""
    <p>Bonjour,</p>
    <p>Merci pour votre commande #{order_ref}.</p>
    <p>Votre facture est disponible ici : <a href=\"{invoice_url}\">{invoice_url}</a></p>
    <p>— L'équipe {store_name}</p>
    """
    await _send_email(to_email, subject, html, template="invoice", store_id=store_id)


async def send_subscription_reminder_email(to_email: str, store_name: str, days_until_expiry: int, *, store_id: int | None = None) -> None:
    subject = f"[AutoCommerce] Rappel — abonnement {store_name} expire dans {days_until_expiry} jours"
    html = f"""
    <p>Bonjour,</p>
    <p>L'abonnement de la boutique <strong>{store_name}</strong> expire dans <strong>{days_until_expiry} jour(s)</strong>.</p>
    <p>Veuillez renouveler votre abonnement pour continuer à bénéficier de nos services.</p>
    <p>— L'équipe AutoCommerce</p>
    """
    await _send_email(to_email, subject, html, template="subscription_reminder", store_id=store_id)
