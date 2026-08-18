"""api/v1/expenses.py — ACTION 6: Spending Tracker CRUD + scan facture IA"""
from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, date, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id as _sid
from config import settings
from models.database import Expense, ExpenseCategory, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/expenses", tags=["Spending Tracker"])


# ── Schemas ───────────────────────────────────────────────────────────────────
class ExpenseIn(BaseModel):
    description: str = Field(..., max_length=500)
    vendor: str | None = None
    amount: float = Field(..., gt=0)
    currency: str = "TND"
    category: ExpenseCategory = ExpenseCategory.other
    note: str | None = None
    expense_date: date
    scanned_from_invoice: bool = False

class ExpenseUpdate(BaseModel):
    description: str | None = None
    vendor: str | None = None
    amount: float | None = None
    category: ExpenseCategory | None = None
    note: str | None = None
    expense_date: date | None = None

class ExpenseOut(BaseModel):
    id: int; description: str; vendor: str | None; amount: float
    currency: str; category: str; note: str | None; expense_date: date
    scanned_from_invoice: bool; created_at: datetime
    class Config: from_attributes = True


# ── CRUD ──────────────────────────────────────────────────────────────────────
@router.get("/", response_model=list[ExpenseOut])
async def list_expenses(days: int = Query(30), category: str | None = None, db: AsyncSession = Depends(get_db)):
    sid = _sid()
    start = datetime.now(UTC).date() - timedelta(days=days)
    stmt = select(Expense).where(Expense.store_id == sid, Expense.expense_date >= start)
    if category:
        try: stmt = stmt.where(Expense.category == ExpenseCategory(category))
        except ValueError: pass
    result = await db.execute(stmt.order_by(Expense.expense_date.desc()))
    return result.scalars().all()


@router.post("/", response_model=ExpenseOut, status_code=201)
async def create_expense(body: ExpenseIn, db: AsyncSession = Depends(get_db)):
    exp = Expense(store_id=_sid(), **body.model_dump())
    db.add(exp); await db.commit(); await db.refresh(exp)
    return exp


@router.get("/summary")
async def get_summary(days: int = Query(30), db: AsyncSession = Depends(get_db)):
    sid = _sid()
    start = datetime.now(UTC).date() - timedelta(days=days)
    prev_start = start - timedelta(days=days)
    res = await db.execute(
        select(Expense.category, func.sum(Expense.amount).label("total"), func.count(Expense.id).label("count"))
        .where(Expense.store_id == sid, Expense.expense_date >= start).group_by(Expense.category)
    )
    by_cat = {r.category.value: {"total": float(r.total), "count": int(r.count)} for r in res.fetchall()}
    total = sum(d["total"] for d in by_cat.values())
    prev = float(await db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(Expense.store_id == sid, Expense.expense_date >= prev_start, Expense.expense_date < start)
    ) or 0)
    META = {
        "supplier":  {"label":"📦 Fournisseurs", "color":"#6366f1"},
        "fixed":     {"label":"🏢 Coûts fixes",  "color":"#0ea5e9"},
        "marketing": {"label":"📢 Marketing",    "color":"#f59e0b"},
        "staff":     {"label":"👥 Personnel",     "color":"#10b981"},
        "logistics": {"label":"🚚 Logistique",   "color":"#ef4444"},
        "other":     {"label":"📦 Autre",         "color":"#8b5cf6"},
    }
    cats = sorted([{**META.get(k,{"label":k,"color":"#6b7280"}), "category":k, **d,
                    "pct": round(d["total"]/total*100,1) if total else 0}
                   for k,d in by_cat.items()], key=lambda x: x.get("total",0), reverse=True)
    return {
        "period_days": days, "total": total, "prev_total": prev,
        "change_pct": round((total-prev)/prev*100,1) if prev else 0,
        "categories": cats, "currency": "TND",
    }


@router.get("/{eid}", response_model=ExpenseOut)
async def get_expense(eid: int, db: AsyncSession = Depends(get_db)):
    exp = await db.get(Expense, eid)
    if not exp or exp.store_id != _sid(): raise HTTPException(404, "Not found")
    return exp


@router.patch("/{eid}", response_model=ExpenseOut)
async def update_expense(eid: int, body: ExpenseUpdate, db: AsyncSession = Depends(get_db)):
    exp = await db.get(Expense, eid)
    if not exp or exp.store_id != _sid(): raise HTTPException(404, "Not found")
    for k, v in body.model_dump(exclude_none=True).items(): setattr(exp, k, v)
    await db.commit(); await db.refresh(exp)
    return exp


@router.delete("/{eid}", status_code=204)
async def delete_expense(eid: int, db: AsyncSession = Depends(get_db)):
    exp = await db.get(Expense, eid)
    if not exp or exp.store_id != _sid(): raise HTTPException(404, "Not found")
    await db.delete(exp); await db.commit()


# ── Scan facture via Claude Vision ─────────────────────────────────────────────
@router.post("/scan", response_model=ExpenseIn)
async def scan_invoice(file: UploadFile = File(...)):
    """ACTION 6: Extraction automatique depuis une facture via Claude Vision.

    HARDENING-FIX (post-sprint review): we now route the upload through
    ``services.upload_security.validate_upload`` so MIME-type spoofing and
    disguised executables are rejected before the bytes ever reach the
    external vision API. We keep the prior 415 contract for unsupported
    formats but add magic-byte + extension whitelisting underneath.
    """
    from config import settings as _settings
    from services.upload_security import UploadRejected, validate_upload

    content = await file.read()
    if not content: raise HTTPException(400, "Fichier vide")
    mtype = file.content_type or "image/jpeg"
    if mtype not in ("image/jpeg","image/png","image/webp","application/pdf"):
        raise HTTPException(415, "Format non supporté. JPEG, PNG ou PDF.")
    # Image vs PDF dispatch — different allowance sets in upload_security.
    _allow = "document" if mtype == "application/pdf" else "image"
    _max_bytes = (
        _settings.UPLOAD_MAX_BYTES_DOCUMENT if _allow == "document"
        else _settings.UPLOAD_MAX_BYTES_IMAGE
    )
    try:
        validate_upload(
            data=content,
            filename=file.filename,
            content_type=mtype,
            tenant_id=_sid() or 0,
            allow=_allow,
            max_bytes=_max_bytes,
        )
    except UploadRejected as exc:
        try:
            from services.metrics import upload_validation_total
            upload_validation_total.labels(allow_kind=_allow, outcome="rejected").inc()
        except Exception as _exc:
            logger.warning("expenses.scan metrics_rejected failed: %s", _exc)
        raise HTTPException(415, f"upload_rejected:{exc}") from exc
    try:
        from services.metrics import upload_validation_total
        upload_validation_total.labels(allow_kind=_allow, outcome="accepted").inc()
    except Exception as _exc:
        logger.warning("expenses.scan metrics_accepted failed: %s", _exc)
    b64 = base64.b64encode(content).decode()
    SYSTEM = (
        'Tu es expert comptable. Analyse cette facture. '
        'Réponds UNIQUEMENT en JSON sans markdown: '
        '{"description":"...","vendor":"...","amount":0.0,"currency":"TND",'
        '"expense_date":"YYYY-MM-DD","category":"supplier|fixed|marketing|staff|logistics|other","note":"..."}'
    )
    try:
        api_key = getattr(settings, "ANTHROPIC_API_KEY", None) or settings.OPENAI_API_KEY
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version":"2023-06-01", "content-type":"application/json"},
                json={"model":"claude-sonnet-4-20250514","max_tokens":500,"system":SYSTEM,
                      "messages":[{"role":"user","content":[
                          {"type":"image","source":{"type":"base64","media_type":mtype,"data":b64}},
                          {"type":"text","text":"Analyse et retourne le JSON demandé."}]}]})
        if r.status_code != 200: raise HTTPException(502, f"Vision API: {r.status_code}")
        text = r.json().get("content",[{}])[0].get("text","")
        parsed = json.loads(text.strip())
        return ExpenseIn(
            description=parsed.get("description","Facture scannée")[:500],
            vendor=parsed.get("vendor"), amount=float(parsed.get("amount",0)),
            currency=parsed.get("currency","TND"),
            category=ExpenseCategory(parsed.get("category","other")),
            note=parsed.get("note"),
            expense_date=date.fromisoformat(parsed.get("expense_date", str(date.today()))),
            scanned_from_invoice=True,
        )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise HTTPException(422, f"Extraction impossible: {e}")
    except HTTPException: raise
    except Exception as e:
        logger.error("scan_invoice: %s", e); raise HTTPException(502, "Erreur analyse facture")
