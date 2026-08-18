"""services/invoice_service.py — factures TVA, avoirs, PDF, export comptable."""
from __future__ import annotations

import csv
import os
from datetime import UTC, datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import AccountingDocument, Order, PaymentLink, Store
from services.tax_service import calculate_manual_amount_taxes, calculate_order_taxes

INVOICE_DIR = Path(os.environ.get("INVOICE_DIR", "/tmp/invoices"))
INVOICE_DIR.mkdir(parents=True, exist_ok=True)


def generate_invoice_number(store_id: int, prefix: str = "INV") -> str:
    now = datetime.now(UTC)
    return f"{prefix}-{store_id:04d}-{now:%Y%m}-{uuid4().hex[:6].upper()}"


def generate_credit_note_number(store_id: int, prefix: str = "AV") -> str:
    now = datetime.now(UTC)
    return f"{prefix}-{store_id:04d}-{now:%Y%m}-{uuid4().hex[:6].upper()}"


def _safe_decimal(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def _safe_store_name(store: Store | None, store_id: int | None = None) -> str:
    if store is None:
        return f"Boutique {store_id or ''}".strip()
    return getattr(store, "legal_name", None) or getattr(store, "name", None) or f"Boutique {getattr(store, 'id', store_id or '')}"


def _document_path(number: str, kind: str) -> Path:
    safe_number = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in number)
    prefix = "credit_note" if kind == "credit_note" else "invoice"
    return INVOICE_DIR / f"{prefix}_{safe_number}.pdf"


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
        ]
    )


def _build_pdf(
    *,
    document_kind: str,
    store: Store,
    document_number: str,
    customer_name: str | None,
    customer_email: str | None,
    customer_phone: str | None,
    description: str | None,
    subtotal_amount: float,
    tax_amount: float,
    total_amount: float,
    currency: str,
    tax_breakdown: list[dict[str, Any]] | None,
    items: list[dict[str, Any]],
    original_document_number: str | None = None,
    issued_at: datetime | None = None,
) -> bytes:
    title = "Avoir" if document_kind == "credit_note" else "Facture TVA"
    issued_at = issued_at or datetime.now(UTC)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    styles = getSampleStyleSheet()
    muted = ParagraphStyle("Muted", parent=styles["Normal"], textColor=colors.HexColor("#475569"), fontSize=9)

    story: list[Any] = []
    story.append(Paragraph(f"<b>{_safe_store_name(store)}</b>", styles["Title"]))
    story.append(Paragraph(title, styles["Heading2"]))
    story.append(Paragraph(f"Numéro : <b>{document_number}</b>", styles["Normal"]))
    story.append(Paragraph(f"Date : {issued_at:%Y-%m-%d %H:%M UTC}", styles["Normal"]))
    if original_document_number:
        story.append(Paragraph(f"Document d'origine : {original_document_number}", styles["Normal"]))
    story.append(Spacer(1, 4 * mm))

    legal_bits = []
    vat_number = getattr(store, "vat_number", None)
    legal_address = getattr(store, "legal_address", None)
    support_email = getattr(store, "support_email", None)
    if vat_number:
        legal_bits.append(f"N° TVA : {vat_number}")
    if legal_address:
        legal_bits.append(f"Adresse légale : {legal_address}")
    if support_email:
        legal_bits.append(f"Email : {support_email}")
    if legal_bits:
        story.append(Paragraph("<br/>".join(legal_bits), muted))
        story.append(Spacer(1, 4 * mm))

    customer_lines = [
        customer_name or "Client non renseigné",
        customer_email or "",
        customer_phone or "",
        description or "",
    ]
    story.append(Paragraph("<b>Client</b>", styles["Heading3"]))
    story.append(Paragraph("<br/>".join([line for line in customer_lines if line]), styles["Normal"]))
    story.append(Spacer(1, 4 * mm))

    rows = [["Produit / Ligne", "Qté", "PU", "HT", "TVA", "TTC"]]
    for item in items:
        qty = item.get("qty", item.get("quantity", 1))
        rows.append(
            [
                str(item.get("name") or item.get("product_name") or item.get("description") or "Ligne"),
                str(qty),
                f"{_safe_decimal(item.get('unit_price')):.2f} {currency}",
                f"{_safe_decimal(item.get('subtotal')):.2f} {currency}",
                f"{_safe_decimal(item.get('tax_amount')):.2f} {currency}",
                f"{_safe_decimal(item.get('total')):.2f} {currency}",
            ]
        )
    if len(rows) == 1:
        rows.append([
            description or "Paiement",
            "1",
            f"{total_amount:.2f} {currency}",
            f"{subtotal_amount:.2f} {currency}",
            f"{tax_amount:.2f} {currency}",
            f"{total_amount:.2f} {currency}",
        ])

    lines_table = Table(rows, colWidths=[70 * mm, 16 * mm, 24 * mm, 24 * mm, 24 * mm, 24 * mm])
    lines_table.setStyle(_table_style())
    story.append(lines_table)
    story.append(Spacer(1, 5 * mm))

    summary_rows = [
        ["Total HT", f"{subtotal_amount:.2f} {currency}"],
        ["TVA", f"{tax_amount:.2f} {currency}"],
        ["Total TTC", f"{total_amount:.2f} {currency}"],
    ]
    summary_table = Table(summary_rows, colWidths=[45 * mm, 35 * mm], hAlign="RIGHT")
    summary_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#e2e8f0")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(summary_table)

    if tax_breakdown:
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("<b>Détail TVA</b>", styles["Heading3"]))
        br_rows = [["Libellé", "Taux", "Base", "TVA", "Catégories"]]
        for entry in tax_breakdown:
            br_rows.append([
                str(entry.get("label") or "TVA"),
                f"{_safe_decimal(entry.get('rate')) * 100:.2f}%",
                f"{_safe_decimal(entry.get('taxable_base')):.2f} {currency}",
                f"{_safe_decimal(entry.get('tax_amount')):.2f} {currency}",
                ", ".join(entry.get("categories") or []),
            ])
        br_table = Table(br_rows, colWidths=[42 * mm, 20 * mm, 32 * mm, 28 * mm, 56 * mm])
        br_table.setStyle(_table_style())
        story.append(br_table)

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "Mentions légales : document généré automatiquement. Conservez-le pour votre comptabilité et vos obligations fiscales.",
        muted,
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


async def _load_order_and_store(db: AsyncSession, store_id: int, order_id: int) -> tuple[Order, Store]:
    order_result = await db.execute(select(Order).where(Order.id == order_id, Order.store_id == store_id))
    order = order_result.scalar_one_or_none()
    if order is None:
        raise ValueError(f"Order {order_id} not found for store {store_id}")
    if hasattr(db, "get"):
        store = await db.get(Store, store_id)
    else:
        store_result = await db.execute(select(Store).where(Store.id == store_id))
        store = store_result.scalar_one_or_none()
    if store is None:
        raise ValueError(f"Store {store_id} not found")
    return order, store


async def _upsert_accounting_document(
    db: AsyncSession,
    *,
    store: Store,
    payment_link: PaymentLink | None,
    order: Order | None,
    document_type: str,
    number: str,
    subtotal_amount: float,
    tax_amount: float,
    total_amount: float,
    currency: str,
    tax_breakdown: list[dict[str, Any]] | None,
    pdf_path: str,
    original_document_number: str | None = None,
) -> AccountingDocument:
    stmt = select(AccountingDocument).where(AccountingDocument.number == number)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    doc = existing or AccountingDocument(
        store_id=store.id,
        payment_link_id=payment_link.id if payment_link else None,
        order_id=order.id if order else None,
        document_type=document_type,
        number=number,
    )
    doc.store_id = store.id
    doc.payment_link_id = payment_link.id if payment_link else None
    doc.order_id = order.id if order else None
    doc.document_type = document_type
    doc.original_document_number = original_document_number
    doc.currency = currency
    doc.subtotal_amount = subtotal_amount
    doc.tax_amount = tax_amount
    doc.total_amount = total_amount
    doc.tax_breakdown = tax_breakdown
    doc.pdf_path = pdf_path
    doc.issued_at = datetime.now(UTC)
    if existing is None:
        db.add(doc)
    await db.flush()
    return doc


async def create_and_save_invoice(
    store_id: int | None = None,
    order_id: int | None = None,
    db: AsyncSession | Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    payment_link: PaymentLink | None = kwargs.get("payment_link")
    store: Store | None = kwargs.get("store")
    order: Order | None = kwargs.get("order")

    if payment_link is None and order is None:
        if store_id is None or order_id is None or db is None:
            raise ValueError("store_id, order_id et db sont requis si payment_link/order absent")
        order, store = await _load_order_and_store(db, store_id, order_id)
    elif payment_link is not None and store is None:
        if db is None:
            raise ValueError("db requis pour charger le store")
        store = await db.get(Store, payment_link.store_id)

    if store is None:
        raise ValueError("Store introuvable pour la facture")

    store_prefix = getattr(store, "invoice_prefix", None) or "INV"

    if payment_link is not None:
        invoice_number = payment_link.invoice_number or generate_invoice_number(getattr(store, "id", 0), prefix=store_prefix)
        result = await calculate_manual_amount_taxes(
            db if isinstance(db, AsyncSession) else None,
            store=store,
            description=payment_link.description or "Paiement en ligne",
            amount=payment_link.amount,
            country_code=payment_link.country_code or getattr(store, "default_tax_country", None) or getattr(store, "country", None),
            customer_email=payment_link.customer_email,
            customer_phone=payment_link.customer_phone,
            prices_include_tax=True,
        )
        payment_link.invoice_number = invoice_number
        payment_link.invoice_url = f"/api/v1/payment-links/{payment_link.id}/invoice"
        payment_link.invoice_pdf_path = str(_document_path(invoice_number, "invoice"))
        payment_link.subtotal_amount = result.subtotal_amount
        payment_link.tax_amount = result.tax_amount
        payment_link.country_code = result.country_code
        payment_link.tax_breakdown = result.breakdown
        items = result.as_dict()["items"]
        subtotal_amount = float(result.subtotal_amount)
        tax_amount = float(result.tax_amount)
        total_amount = float(result.total_amount)
        currency = payment_link.currency or "EUR"
        customer_name = payment_link.customer_name
        customer_email = payment_link.customer_email
        customer_phone = payment_link.customer_phone
        description = payment_link.description
    else:
        assert order is not None
        invoice_number = generate_invoice_number(store.id, prefix=store_prefix)
        result = await calculate_order_taxes(
            db if isinstance(db, AsyncSession) else None,
            store=store,
            order=order,
        )
        order.subtotal_amount = result.subtotal_amount
        order.tax_amount = result.tax_amount
        order.country_code = result.country_code
        order.tax_breakdown = result.breakdown
        if not getattr(order, "currency", None):
            order.currency = "TND" if (result.country_code or "") == "TN" else "EUR"
        items = result.as_dict()["items"]
        subtotal_amount = float(result.subtotal_amount)
        tax_amount = float(result.tax_amount)
        total_amount = float(result.total_amount)
        currency = getattr(order, "currency", None) or "EUR"
        customer_name = getattr(order, "delivery_name", None)
        customer_email = None
        customer_phone = None
        description = getattr(order, "notes", None)

    pdf_path = _document_path(invoice_number, "invoice")
    pdf_bytes = _build_pdf(
        document_kind="invoice",
        store=store,
        document_number=invoice_number,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        description=description,
        subtotal_amount=subtotal_amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
        currency=currency,
        tax_breakdown=result.breakdown,
        items=items,
    )
    pdf_path.write_bytes(pdf_bytes)

    if isinstance(db, AsyncSession):
        await _upsert_accounting_document(
            db,
            store=store,
            payment_link=payment_link,
            order=order,
            document_type="invoice",
            number=invoice_number,
            subtotal_amount=subtotal_amount,
            tax_amount=tax_amount,
            total_amount=total_amount,
            currency=currency,
            tax_breakdown=result.breakdown,
            pdf_path=str(pdf_path),
        )

    return {
        "status": "generated",
        "invoice_number": invoice_number,
        "invoice_url": f"/api/v1/payment-links/{payment_link.id}/invoice" if payment_link is not None else None,
        "pdf_path": str(pdf_path),
        "pdf_bytes": pdf_bytes,
        "subtotal_amount": subtotal_amount,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "tax_breakdown": result.breakdown,
        "currency": currency,
    }


async def create_credit_note_for_payment_link(
    db: AsyncSession,
    *,
    payment_link: PaymentLink,
    store: Store,
    refund_amount: float | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    number = generate_credit_note_number(getattr(store, "id", 0), prefix=getattr(store, "credit_note_prefix", None) or "AV")
    source_total = _safe_decimal(payment_link.amount)
    source_subtotal = _safe_decimal(payment_link.subtotal_amount)
    source_tax = _safe_decimal(payment_link.tax_amount)

    amount = min(refund_amount or source_total, source_total)
    ratio = (amount / source_total) if source_total else 1.0
    subtotal_amount = round(source_subtotal * ratio, 4)
    tax_amount = round(source_tax * ratio, 4)
    breakdown = []
    for entry in payment_link.tax_breakdown or []:
        breakdown.append({
            **entry,
            "taxable_base": round(_safe_decimal(entry.get("taxable_base")) * ratio, 2),
            "tax_amount": round(_safe_decimal(entry.get("tax_amount")) * ratio, 2),
            "total": round(_safe_decimal(entry.get("total")) * ratio, 2),
        })

    items = [
        {
            "name": reason or f"Avoir sur {payment_link.invoice_number or payment_link.id}",
            "qty": 1,
            "unit_price": amount,
            "subtotal": subtotal_amount,
            "tax_amount": tax_amount,
            "total": amount,
        }
    ]
    pdf_path = _document_path(number, "credit_note")
    pdf_bytes = _build_pdf(
        document_kind="credit_note",
        store=store,
        document_number=number,
        customer_name=payment_link.customer_name,
        customer_email=payment_link.customer_email,
        customer_phone=payment_link.customer_phone,
        description=reason or "Avoir client",
        subtotal_amount=subtotal_amount,
        tax_amount=tax_amount,
        total_amount=amount,
        currency=payment_link.currency,
        tax_breakdown=breakdown,
        items=items,
        original_document_number=payment_link.invoice_number,
    )
    pdf_path.write_bytes(pdf_bytes)

    doc = await _upsert_accounting_document(
        db,
        store=store,
        payment_link=payment_link,
        order=None,
        document_type="credit_note",
        number=number,
        subtotal_amount=subtotal_amount,
        tax_amount=tax_amount,
        total_amount=amount,
        currency=payment_link.currency,
        tax_breakdown=breakdown,
        pdf_path=str(pdf_path),
        original_document_number=payment_link.invoice_number,
    )
    await db.commit()
    return {
        "status": "generated",
        "credit_note_number": number,
        "pdf_path": str(pdf_path),
        "pdf_bytes": pdf_bytes,
        "accounting_document_id": doc.id,
    }


def generate_invoice_pdf(**kwargs: Any) -> str:
    store = Store(
        id=kwargs.get("store_id") or 0,
        name=kwargs.get("store_name") or "Boutique",
        legal_name=kwargs.get("store_name") or "Boutique",
        slug="tmp-store",
    )
    if kwargs.get("store_email"):
        store.support_email = kwargs["store_email"]
    if kwargs.get("store_country"):
        store.default_tax_country = kwargs["store_country"]
    number = kwargs["invoice_number"]
    path = _document_path(number, "invoice")
    pdf_bytes = _build_pdf(
        document_kind="invoice",
        store=store,
        document_number=number,
        customer_name=kwargs.get("customer_name"),
        customer_email=kwargs.get("customer_email"),
        customer_phone=kwargs.get("customer_phone"),
        description=kwargs.get("description"),
        subtotal_amount=_safe_decimal(kwargs.get("amount")) - _safe_decimal(kwargs.get("tax_amount")),
        tax_amount=_safe_decimal(kwargs.get("tax_amount")),
        total_amount=_safe_decimal(kwargs.get("amount")),
        currency=kwargs.get("currency") or "EUR",
        tax_breakdown=kwargs.get("tax_breakdown") or [],
        items=[
            {
                "name": kwargs.get("description") or "Paiement",
                "qty": 1,
                "unit_price": _safe_decimal(kwargs.get("amount")),
                "subtotal": _safe_decimal(kwargs.get("amount")) - _safe_decimal(kwargs.get("tax_amount")),
                "tax_amount": _safe_decimal(kwargs.get("tax_amount")),
                "total": _safe_decimal(kwargs.get("amount")),
            }
        ],
        issued_at=kwargs.get("created_at") or datetime.now(UTC),
    )
    path.write_bytes(pdf_bytes)
    return str(path)


async def export_accounting_csv(db: AsyncSession, *, store_id: int, from_date: datetime | None = None, to_date: datetime | None = None) -> str:
    stmt = select(AccountingDocument).where(AccountingDocument.store_id == store_id)
    if from_date is not None:
        stmt = stmt.where(AccountingDocument.issued_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(AccountingDocument.issued_at <= to_date)
    stmt = stmt.order_by(AccountingDocument.issued_at.desc(), AccountingDocument.id.desc())

    result = await db.execute(stmt)
    docs = result.scalars().all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "document_type",
        "number",
        "original_document_number",
        "issued_at",
        "currency",
        "subtotal_amount",
        "tax_amount",
        "total_amount",
        "payment_link_id",
        "order_id",
        "pdf_path",
    ])
    for doc in docs:
        writer.writerow([
            doc.document_type,
            doc.number,
            doc.original_document_number or "",
            doc.issued_at.isoformat() if doc.issued_at else "",
            doc.currency,
            doc.subtotal_amount,
            doc.tax_amount,
            doc.total_amount,
            doc.payment_link_id or "",
            doc.order_id or "",
            doc.pdf_path or "",
        ])
    return output.getvalue()
