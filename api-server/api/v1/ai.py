"""api/v1/ai.py — AI utility endpoints (vision test, product search)"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id as _sid
from api.v1._deps import require_role
from middleware.tenant import current_tenant_id
from models.database import get_db
from services.embedding_search import find_best_match, search_products
from services.vision_analyzer import analyze_image_bytes, analyze_image_url

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/ai",
    tags=["AI"],
    dependencies=[require_role("viewer")],  # BUG#3 FIX: enforce valid JWT + recognized role
)


# ─── Test vision with uploaded image ─────────────────────────────────────────
@router.post("/vision/upload")
async def test_vision_upload(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload an image and test the full vision -> product match pipeline.

    HARDENING-FIX (post-sprint review): the previous handler only checked the
    Content-Type prefix and the byte length — it had no magic-byte validation,
    no extension whitelist, and no defence against disguised executables (a
    `.php` renamed `.jpg` with the right Content-Type would have reached the
    vision model). We now delegate to ``services.upload_security.validate_upload``
    which enforces extension+MIME whitelist, magic bytes, SVG XSS guard,
    tenant-scoped path and randomised filenames. The analysis call still
    receives the raw bytes — no breaking change for the existing contract.
    """
    from config import settings as _settings
    from services.upload_security import UploadRejected, validate_upload

    store_id = _sid()

    image_bytes = await file.read()
    try:
        validate_upload(
            data=image_bytes,
            filename=file.filename,
            content_type=file.content_type,
            tenant_id=store_id or 0,
            allow="image",
            max_bytes=_settings.UPLOAD_MAX_BYTES_IMAGE,
        )
    except UploadRejected as exc:
        try:
            from services.metrics import upload_validation_total
            upload_validation_total.labels(allow_kind="image", outcome="rejected").inc()
        except Exception as _exc:
            logger.warning("operation failed: %s", _exc)
            pass
        raise HTTPException(status_code=400, detail=f"upload_rejected:{exc}") from exc
    try:
        from services.metrics import upload_validation_total
        upload_validation_total.labels(allow_kind="image", outcome="accepted").inc()
    except Exception as _exc:
        logger.warning("operation failed: %s", _exc)
        pass

    # Vision analysis
    vision = await analyze_image_bytes(image_bytes)

    # Product match
    match = await find_best_match(db, store_id, vision)

    return {
        "vision_analysis": vision,
        "stock_match": match,
    }


# ─── Test vision with URL ─────────────────────────────────────────────────────
class VisionUrlRequest(BaseModel):
    image_url: str
    search_stock: bool = True


@router.post("/vision/url")
async def test_vision_url(
    body: VisionUrlRequest,
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    vision = await analyze_image_url(body.image_url)

    result = {"vision_analysis": vision}
    if body.search_stock:
        result["stock_match"] = await find_best_match(db, store_id, vision)

    return result


# ─── Semantic product search ──────────────────────────────────────────────────
class SemanticSearchRequest(BaseModel):
    # HIGH-11 FIX: limite de taille sur le champ query.
    # Sans limite, un client malveillant peut envoyer 1 MB de texte tokenisé
    # et envoyé au LLM -> coûts élevés non tracés dans les quotas tenant.
    query: str = Field(..., max_length=500, description="Texte de recherche (max 500 caractères)")
    top_k: int = Field(5, ge=1, le=50, description="Nombre de résultats (max 50)")


@router.post("/search")
async def semantic_search(
    body: SemanticSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    vision_like = {
        "type": body.query,
        "color": "",
        "brand": None,
        "keywords": body.query.split(),
    }
    results = await search_products(db, store_id, vision_like, top_k=body.top_k)
    return {"query": body.query, "results": results, "count": len(results)}


# ─── Bug4 FIX: Backend proxy endpoints for Dashboard AI features ──────────────
# These replace direct browser->Anthropic calls which exposed API keys and failed
# silently (no Authorization header was sent).

class ScanInvoiceRequest(BaseModel):
    # HIGH-11 FIX: limite taille base64 image (~5MB décodé = ~6.7MB base64)
    image_base64: str = Field(..., max_length=7_000_000, description="Image en base64 (max ~5 MB décodé)")
    media_type: str = Field("image/jpeg", pattern=r"^image/(jpeg|png|webp|gif)$")


@router.post("/scan-invoice")
async def scan_invoice(
    body: ScanInvoiceRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Bug4 FIX: Proxy invoice scanning via backend.
    Uses the vision analyzer service (tenant-aware AI key).
    """
    from middleware.tenant import current_tenant_id
    from services.vision_analyzer import analyze_image_base64

    store_id = _sid() or 0

    try:
        result = await analyze_image_base64(
            image_base64=body.image_base64,
            media_type=body.media_type,
            prompt=(
                "Tu es un expert comptable. Analyse cette facture et extrais les informations. "
                "Réponds UNIQUEMENT en JSON valide (sans markdown) avec ce format exact: "
                '{"desc": "description courte", "vendor": "nom fournisseur", '
                '"amount": 99.99, "date": "2026-04-25", '
                '"cat": "supplier|fixed|marketing|staff|logistics|other", "note": "détails"}'
            ),
            store_id=store_id,
            db=db,
        )
        import json
        import re as _re
        clean = _re.sub(r"```json|```", "", result).strip()
        parsed = json.loads(clean)
        return parsed
    except Exception as e:
        import logging
        logging.getLogger("ai").warning("scan_invoice failed: %s", e)
        raise HTTPException(502, "Analyse de facture indisponible")


class SpendingInsightRequest(BaseModel):
    budget: float = Field(..., ge=0)
    total_spent: float = Field(..., ge=0)
    remaining: float
    # HIGH-11 FIX: top_categories est injecté dans un prompt LLM — limite à 200 chars
    top_categories: str = Field(..., max_length=200)
    expense_count: int = Field(..., ge=0, le=100_000)


@router.post("/spending-insight")
async def spending_insight(
    body: SpendingInsightRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Bug4 FIX: Proxy spending insight generation via backend.
    Uses the LLM gateway (tenant-aware AI key).
    """
    from middleware.tenant import current_tenant_id
    from services.llm_gateway import chat

    _sid() or 0

    prompt = (
        f"Budget: {body.budget:.0f} TND | Dépensé: {body.total_spent:.0f} TND | "
        f"Reste: {body.remaining:.0f} TND\n"
        f"Top catégories: {body.top_categories}\n"
        f"Nombre de dépenses: {body.expense_count}\n"
        f"Donne 1 insight pertinent et 1 recommandation concrète pour cette activité."
    )

    try:
        response = await chat(
            messages=[{"role": "user", "content": prompt}],
            system="Tu es un conseiller financier expert pour PME tunisiennes. "
                   "Réponds en français, 3 phrases max, ton professionnel et direct. Pas de preamble.",
            agent_name="spending_insight",
            channel="dashboard",
        )
        content = response.choices[0].message.content if response.choices else ""
        return {"insight": content}
    except Exception as e:
        import logging
        logging.getLogger("ai").warning("spending_insight failed: %s", e)
        return {"insight": "Analyse IA indisponible."}
