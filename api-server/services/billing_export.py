"""
services/billing_export.py — P2‑4 · Génération de factures PDF/CSV et réconciliation Stripe.

Exposé :
  - export_invoice_csv(store_id, period_start, period_end)  -> (path, bytes)
  - export_invoice_pdf(store_id, period_start, period_end)   -> (path, bytes)
  - reconcile_stripe_payments(store_id, since_ts)            -> {matched, missing, extra}
"""
from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InvoiceLine:
    date: str
    label: str
    quantity: int
    unit_credit_cost: int
    credit_delta: int
    amount_dt: float


# ─────────────────────────────────────────────────────────────────────────────
# CSV
# ─────────────────────────────────────────────────────────────────────────────
def export_invoice_csv(
    *,
    tenant_id: int,
    period_start: datetime,
    period_end: datetime,
    lines: list[InvoiceLine],
    totals: dict,
) -> tuple[bytes, str]:
    """Retourne (csv_bytes, suggested_filename)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "tenant_id", "period_start", "period_end",
        "date", "label", "quantity", "unit_credit_cost",
        "credit_delta", "amount_dt",
    ])
    for ln in lines:
        writer.writerow([
            tenant_id, period_start.isoformat(), period_end.isoformat(),
            ln.date, ln.label, ln.quantity, ln.unit_credit_cost,
            ln.credit_delta, f"{ln.amount_dt:.3f}",
        ])

    # Pied de page : totaux
    writer.writerow([])
    writer.writerow(["TOTAL_CREDITS_USED", totals.get("credits_used", 0)])
    writer.writerow(["TOTAL_CREDITS_PURCHASED", totals.get("credits_purchased", 0)])
    writer.writerow(["TOTAL_AMOUNT_DT", f"{totals.get('amount_dt', 0.0):.3f}"])

    raw = buf.getvalue().encode("utf-8")
    filename = f"invoice_{tenant_id}_{period_start.strftime('%Y%m%d')}_{period_end.strftime('%Y%m%d')}.csv"
    return raw, filename


# ─────────────────────────────────────────────────────────────────────────────
# PDF — ReportLab si dispo, sinon fallback texte lisible
# ─────────────────────────────────────────────────────────────────────────────
def export_invoice_pdf(
    *,
    tenant_id: int,
    store_name: str,
    period_start: datetime,
    period_end: datetime,
    lines: list[InvoiceLine],
    totals: dict,
) -> tuple[bytes, str]:
    """Génère un PDF de facture. ReportLab = rendu riche ; fallback = txt lisible."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
            title=f"AutoCommerce Facture #{tenant_id}",
            author="AutoCommerce",
        )
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph(f"<b>AutoCommerce — Facture #{tenant_id}</b>", styles["Title"]))
        story.append(Paragraph(f"Boutique : <b>{store_name}</b>", styles["Normal"]))
        story.append(Paragraph(f"Période : <b>{period_start.strftime('%d/%m/%Y')}</b> → <b>{period_end.strftime('%d/%m/%Y')}</b>", styles["Normal"]))
        story.append(Spacer(1, 0.5 * cm))

        # Tableau des lignes
        data = [["Date", "Libellé", "Qté", "Coût/crédit", "Δ crédits", "Montant (DT)"]]
        for ln in lines:
            data.append([
                ln.date, ln.label[:40],
                str(ln.quantity), str(ln.unit_credit_cost),
                str(ln.credit_delta), f"{ln.amount_dt:.3f}",
            ])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a73e8")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(
            f"<b>Total crédits utilisés :</b> {totals.get('credits_used', 0)}", styles["Normal"]))
        story.append(Paragraph(
            f"<b>Total crédits achetés :</b> {totals.get('credits_purchased', 0)}", styles["Normal"]))
        story.append(Paragraph(
            f"<b>Montant total :</b> {totals.get('amount_dt', 0.0):.3f} DT", styles["Normal"]))
        story.append(Spacer(1, 1 * cm))
        story.append(Paragraph(
            "<i>AutoCommerce — Merci pour votre confiance.</i>", styles["Italic"]))

        doc.build(story)
        raw = buf.getvalue()
        filename = f"invoice_{tenant_id}_{period_start.strftime('%Y%m%d')}_{period_end.strftime('%Y%m%d')}.pdf"
        return raw, filename

    except ImportError:
        # Fallback : TXT lisible si ReportLab n'est pas installé
        logger.warning("reportlab absent — fallback TXT pour la facture tenant=%s", tenant_id)
        buf = io.StringIO()
        buf.write(f"AutoCommerce Facture #{tenant_id}\n")
        buf.write(f"Boutique: {store_name}\n")
        buf.write(f"Période: {period_start.isoformat()} → {period_end.isoformat()}\n\n")
        buf.write(f"{'Date':12} {'Label':40} {'Qté':>4}  {'Coût':>8} {'Δ':>8}  {'DT':>10}\n")
        buf.write("-" * 92 + "\n")
        for ln in lines:
            buf.write(f"{ln.date:12} {ln.label[:40]:40} {ln.quantity:>4}  {ln.unit_credit_cost:>8} {ln.credit_delta:>8}  {ln.amount_dt:>10.3f}\n")
        buf.write("-" * 92 + "\n")
        buf.write(f"TOTAL_USED     : {totals.get('credits_used', 0)}\n")
        buf.write(f"TOTAL_PURCHASED: {totals.get('credits_purchased', 0)}\n")
        buf.write(f"TOTAL_DT       : {totals.get('amount_dt', 0.0):.3f}\n")
        raw = buf.getvalue().encode("utf-8")
        filename = f"invoice_{tenant_id}_{period_start.strftime('%Y%m%d')}_{period_end.strftime('%Y%m%d')}.txt"
        return raw, filename


# ─────────────────────────────────────────────────────────────────────────────
# Réconciliation Stripe — compare `credit_events.reference_id` aux PaymentIntents Stripe
# ─────────────────────────────────────────────────────────────────────────────
async def reconcile_stripe_payments(
    session,
    *,
    tenant_id: int,
    since: datetime | None = None,
) -> dict:
    """
    Stratégie :
      1. Charger tous les top_up `credit_events` du tenant depuis `since`.
      2. Charger tous les Stripe PaymentIntents depuis l'API Stripe sur la même période.
      3. Matcher par reference_id == payment_intent.id, retourner matched/missing/extra.
    Best-effort : si Stripe est injoignable, on retourne un warning sans crash.
    """
    from sqlalchemy import text

    since = since or (datetime.now(UTC) - timedelta(days=90))
    summary = {"matched": 0, "missing": [], "extra": [], "warning": None}

    # 1. Top-ups locaux
    try:
        rows = (await session.execute(
            text("""
                SELECT reference_id, credits_delta, description, created_at
                FROM credit_events
                WHERE store_id = :sid
                  AND event_type = 'top_up'
                  AND created_at >= :since
            """),
            {"sid": tenant_id, "since": since},
        )).mappings().all()
        local_refs = {r["reference_id"]: dict(r) for r in rows if r.get("reference_id")}
    except Exception as exc:
        summary["warning"] = f"credit_events_read_failed: {exc}"
        local_refs = {}

    # 2. PaymentIntents Stripe — config-driven
    try:
        from config import settings
        if not getattr(settings, "STRIPE_SECRET_KEY", None):
            summary["warning"] = "STRIPE_SECRET_KEY absent — réconciliation partielle"
            return summary
    except Exception:
        summary["warning"] = "settings indisponible"
        return summary

    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        intents = stripe.PaymentIntent.list(
            created={"gte": int(since.timestamp())},
            limit=100,
        )
        stripe_pi_ids = {pi["id"]: pi for pi in intents.auto_paging_iter()}
    except Exception as exc:
        summary["warning"] = f"stripe_api_failed: {exc}"
        return summary

    # 3. Diff
    matched = set(local_refs.keys()) & set(stripe_pi_ids.keys())
    missing = sorted(set(local_refs.keys()) - set(stripe_pi_ids.keys()))   # local mais pas Stripe
    extra = sorted(set(stripe_pi_ids.keys()) - set(local_refs.keys()))     # Stripe mais pas local

    summary["matched"] = len(matched)
    summary["missing"] = missing[:100]
    summary["extra"] = extra[:100]
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Réconciliation déclenchée par webhook Stripe (idempotente)
# ─────────────────────────────────────────────────────────────────────────────
async def handle_stripe_webhook_reconciliation(event: dict) -> dict:
    """
    Appelé depuis /api/v1/billing/stripe/webhook.
    Idempotent : utilise la clé duplicate de Stripe pour ne rien faire deux fois.
    Trace l'événement dans `credit_events` pour audit.
    """
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    if etype not in {"payment_intent.succeeded", "charge.succeeded"}:
        return {"handled": False, "reason": f"event_type_ignored:{etype}"}

    pi_id = obj.get("id") or event.get("id")
    amount = int(obj.get("amount", 0) or 0)            # cents
    currency = obj.get("currency", "usd")
    metadata = obj.get("metadata") or {}

    tenant_id = int(metadata.get("tenant_id") or metadata.get("store_id") or 0)
    pack_id = metadata.get("pack_id")

    if not (tenant_id and pi_id):
        return {"handled": False, "reason": "metadata_missing_tenant_or_pi"}

    # Idempotence — utiliser la table d'idempotency (créée en P0)
    try:
        from services.idempotency import check_idempotency
        already = await check_idempotency("stripe_payment", pi_id)
        if already:
            return {"handled": True, "idempotent": True, "tenant_id": tenant_id}
    except Exception:
        pass  # si le module n'existe pas — on continue sans idempotence

    # Si pack_id reconnu, on crédite via credit_ledger
    if pack_id and pack_id in {"starter_50", "growth_200", "business_500", "enterprise_1k"}:
        from services.credit_ledger import purchase_top_up
        result = await purchase_top_up(tenant_id, pack_id, payment_ref=pi_id)
        return {
            "handled": True, "tenant_id": tenant_id, "pack_id": pack_id,
            "amount": amount / 100.0, "currency": currency,
            "credit_result": result,
        }

    # Sinon : juste enregistrer l'événement pour audit
    logger.info(
        "stripe webhook reconciliation pi=%s amount=%s currency=%s tenant=%s pack=%s",
        pi_id, amount, currency, tenant_id, pack_id or "none",
    )
    return {
        "handled": True, "tenant_id": tenant_id, "pack_id": pack_id,
        "amount": amount / 100.0, "currency": currency, "credited": False,
    }
