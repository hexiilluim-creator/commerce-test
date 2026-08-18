"""services/vin_decoder.py — Décodeur VIN et identificateur de véhicules.

Stratégie multi-source :
  1. OCR + parsing sur image carte grise (via vision LLM).
  2. Extraction textuelle NLP (marque / modèle / année depuis texte libre).
  3. Lookup NHTSA vPIC API (gratuit, sans clé) pour enrichissement VIN.
  4. Fallback LLM si les heuristiques échouent.

Interface publique :
  VehicleInfo                — dataclass de résultat
  extract_from_text(text)    -> VehicleInfo
  extract_from_image(bytes, mime_type) -> VehicleInfo
  decode_vin(vin)            -> VehicleInfo   (lookup NHTSA)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

NHTSA_VIN_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{vin}?format=json"
NHTSA_TIMEOUT = 8.0  # secondes

# Marques automobiles courantes (FR + arabe darija)
_MAKE_ALIASES: dict[str, str] = {
    "vw": "Volkswagen", "volkswagen": "Volkswagen",
    "merco": "Mercedes", "mercedes": "Mercedes", "benz": "Mercedes",
    "bmw": "BMW",
    "pejo": "Peugeot", "peugeot": "Peugeot", "206": "Peugeot", "207": "Peugeot", "208": "Peugeot",
    "renault": "Renault", "clio": "Renault", "dacia": "Dacia", "logan": "Dacia",
    "citro": "Citroën", "citroën": "Citroën", "citroen": "Citroën",
    "hyundai": "Hyundai", "tucson": "Hyundai", "elantra": "Hyundai",
    "kia": "Kia", "picanto": "Kia", "sportage": "Kia",
    "toyota": "Toyota", "yaris": "Toyota", "corolla": "Toyota",
    "fiat": "Fiat", "tipo": "Fiat", "punto": "Fiat",
    "ford": "Ford", "focus": "Ford", "fiesta": "Ford",
    "seat": "Seat", "ibiza": "Seat", "leon": "Seat",
    "opel": "Opel", "astra": "Opel", "corsa": "Opel",
    "skoda": "Skoda", "octavia": "Skoda", "fabia": "Skoda",
    "honda": "Honda", "civic": "Honda", "jazz": "Honda",
    "nissan": "Nissan", "qashqai": "Nissan", "juke": "Nissan",
    "mazda": "Mazda",
    "suzuki": "Suzuki",
    "mitsubishi": "Mitsubishi",
    "lancia": "Lancia",
    "alfa": "Alfa Romeo", "alfa romeo": "Alfa Romeo",
}

# Regex VIN standard (17 chars alphanum, sans I O Q)
_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")

# Regex année (1970-2030)
_YEAR_RE = re.compile(r"\b(19[7-9]\d|20[0-3]\d)\b")


# ── Dataclass résultat ────────────────────────────────────────────────────────

@dataclass
class VehicleInfo:
    """Informations identifiées sur un véhicule."""
    make:        str | None = None   # Marque  (ex: "Peugeot")
    model:       str | None = None   # Modèle  (ex: "206")
    year:        str | None = None   # Année   (ex: "2018")
    engine:      str | None = None   # Motorisation (ex: "1.6 HDi")
    vin:         str | None = None   # Numéro VIN complet
    confidence:  float      = 0.0    # 0.0-1.0
    source:      str        = "unknown"  # "nhtsa" | "llm" | "heuristic" | "ocr"

    def is_complete(self) -> bool:
        """Retourne True si on a au minimum marque + modèle ou marque + année."""
        if self.vin:
            return True
        return bool(self.make and (self.model or self.year))

    def summary(self) -> str:
        """Résumé court pour les messages WhatsApp."""
        parts = []
        if self.make:
            parts.append(self.make)
        if self.model:
            parts.append(self.model)
        if self.year:
            parts.append(self.year)
        if self.engine:
            parts.append(self.engine)
        return " ".join(parts) if parts else "Véhicule inconnu"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Heuristiques rapides ──────────────────────────────────────────────────────

def _extract_vin(text: str) -> str | None:
    m = _VIN_RE.search(text.upper())
    return m.group(1) if m else None


def _extract_year(text: str) -> str | None:
    m = _YEAR_RE.search(text)
    if not m:
        return None
    # Le regex accepte 2000-2039 (large exprès pour ne pas re-hardcoder une
    # borne qui vieillirait mal). On valide le "trop loin dans le futur" ici,
    # dynamiquement : une année-modèle dépasse rarement current_year + 1.
    year = int(m.group(1))
    max_valid_year = datetime.now(UTC).year + 1
    if year > max_valid_year:
        return None
    return m.group(1)


def _extract_make(text: str) -> str | None:
    lower = text.lower()
    # Chercher d'abord les alias multi-mots
    for alias, make in sorted(_MAKE_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lower:
            return make
    return None


# ── NHTSA vPIC API ────────────────────────────────────────────────────────────

async def decode_vin(vin: str) -> VehicleInfo:
    """Décode un VIN via l'API NHTSA (gratuite, sans clé API).

    Retourne un VehicleInfo avec source="nhtsa".
    En cas d'erreur réseau, retourne un VehicleInfo minimal avec le VIN.
    """
    vin = vin.strip().upper()
    try:
        async with httpx.AsyncClient(timeout=NHTSA_TIMEOUT) as client:
            resp = await client.get(NHTSA_VIN_URL.format(vin=vin))
            resp.raise_for_status()
            data = resp.json()

        results = data.get("Results", [])
        # NHTSA retourne une liste de {Variable, Value, VariableId}
        fields: dict[str, str] = {
            r["Variable"]: r["Value"]
            for r in results
            if r.get("Value") and r["Value"] not in ("", "Not Applicable", "0")
        }

        make  = fields.get("Make") or fields.get("Manufacturer Name")
        model = fields.get("Model")
        year  = fields.get("Model Year")
        engine_displacement = fields.get("Displacement (L)")
        fuel_type = fields.get("Fuel Type - Primary")

        engine_parts = []
        if engine_displacement:
            engine_parts.append(f"{engine_displacement}L")
        if fuel_type:
            engine_parts.append(fuel_type)
        engine = " ".join(engine_parts) if engine_parts else None

        return VehicleInfo(
            make=make,
            model=model,
            year=str(year) if year else None,
            engine=engine,
            vin=vin,
            confidence=0.95,
            source="nhtsa",
        )

    except Exception as exc:
        logger.warning("NHTSA VIN decode failed for %s: %s", vin, exc)
        return VehicleInfo(vin=vin, confidence=0.3, source="nhtsa_failed")


# ── Prompt LLM pour extraction textuelle ─────────────────────────────────────

_TEXT_EXTRACT_PROMPT = """Extrais les informations du véhicule depuis ce texte.
Le texte peut être en français, arabe ou darija tunisienne.

Retourne UNIQUEMENT un JSON valide :
{
  "make": "marque ou null",
  "model": "modèle ou null",
  "year": "année (4 chiffres) ou null",
  "engine": "motorisation ou null",
  "vin": "numéro VIN 17 caractères ou null",
  "confidence": 0.0 à 1.0
}

Exemples :
- "clio 2015 essence" -> {"make": "Renault", "model": "Clio", "year": "2015", "engine": "Essence", ...}
- "206 HDi 2008" -> {"make": "Peugeot", "model": "206", "year": "2008", "engine": "HDi", ...}
- "فولكسفاغن غولف 2019" -> {"make": "Volkswagen", "model": "Golf", "year": "2019", ...}
"""

_IMAGE_EXTRACT_PROMPT = """Tu regardes une image d'une carte grise (carte d'immatriculation) ou d'un document véhicule.
Extrais les informations du véhicule visibles dans l'image.

Retourne UNIQUEMENT un JSON valide :
{
  "make": "marque ou null",
  "model": "modèle ou null",
  "year": "année de mise en circulation (4 chiffres) ou null",
  "engine": "motorisation/cylindrée ou null",
  "vin": "numéro VIN 17 caractères si visible ou null",
  "confidence": 0.0 à 1.0
}

Cherche particulièrement :
- Champ D.1 (marque), D.2 (type), D.3 (variante)
- Champ B (date 1ère immatriculation)
- Champ E (VIN / numéro de châssis)
- Champ P.1 (cylindrée cm3), P.3 (puissance kW)
"""


# ── Extraction depuis texte ────────────────────────────────────────────────────

async def extract_from_text(text: str) -> VehicleInfo:
    """Extrait les infos véhicule depuis un texte libre.

    Stratégie :
      1. Heuristiques rapides (regex + dictionnaire marques).
      2. Si VIN trouvé -> decode_vin() via NHTSA.
      3. Si heuristiques insuffisantes -> LLM fallback.
    """
    if not text or not text.strip():
        return VehicleInfo()

    # 1. VIN direct ?
    vin = _extract_vin(text)
    if vin:
        info = await decode_vin(vin)
        if info.is_complete():
            return info

    # 2. Heuristiques
    make = _extract_make(text)
    year = _extract_year(text)

    if make and year:
        # Assez pour identifier le véhicule
        # Essayer d'extraire le modèle depuis le texte restant
        model = _extract_model_hint(text, make)
        return VehicleInfo(
            make=make, model=model, year=year,
            confidence=0.75, source="heuristic",
        )

    # 3. Fallback LLM
    return await _llm_extract_text(text)


async def _llm_extract_text(text: str) -> VehicleInfo:
    """Fallback LLM pour extraction textuelle complexe."""
    try:
        from services import llm_gateway
        r = await llm_gateway.chat(
            messages=[
                {"role": "system", "content": _TEXT_EXTRACT_PROMPT},
                {"role": "user", "content": text},
            ],
            agent_name="vin_decoder.text",
            max_tokens=200,
            temperature=0,
        )
        raw = r.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "")
        data = json.loads(raw)

        # Si un VIN est trouvé, enrichir via NHTSA
        if data.get("vin"):
            nhtsa = await decode_vin(data["vin"])
            if nhtsa.is_complete():
                return nhtsa

        return VehicleInfo(
            make=data.get("make"),
            model=data.get("model"),
            year=str(data["year"]) if data.get("year") else None,
            engine=data.get("engine"),
            vin=data.get("vin"),
            confidence=float(data.get("confidence", 0.7)),
            source="llm",
        )
    except Exception as exc:
        logger.warning("LLM text extraction failed: %s", exc)
        return VehicleInfo(confidence=0.0, source="failed")


def _extract_model_hint(text: str, make: str) -> str | None:
    """Tente d'extraire le modèle en cherchant un mot après la marque."""
    lower = text.lower()
    make_lower = make.lower()
    idx = lower.find(make_lower)
    if idx >= 0:
        after = text[idx + len(make_lower):].strip()
        token = after.split()[0] if after.split() else None
        if token and len(token) >= 2 and token.isalnum():
            return token.capitalize()
    return None


# ── Extraction depuis image ───────────────────────────────────────────────────

async def extract_from_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> VehicleInfo:
    """Extrait les infos véhicule depuis une image (carte grise, etc.)

    Utilise le LLM vision (GPT-4o-mini vision ou DeepSeek-VL si disponible).
    Enrichit avec NHTSA si un VIN est trouvé.
    """
    import base64

    if not image_bytes:
        return VehicleInfo()

    b64 = base64.b64encode(image_bytes).decode()

    try:
        from services import llm_gateway

        # Appel vision via LLM gateway (passe par le même circuit breaker / quota)
        r = await llm_gateway.chat(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64}",
                                "detail": "high",
                            },
                        },
                        {
                            "type": "text",
                            "text": _IMAGE_EXTRACT_PROMPT,
                        },
                    ],
                }
            ],
            agent_name="vin_decoder.image",
            max_tokens=300,
            temperature=0,
        )

        raw = r.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "")
        data = json.loads(raw)

        # Enrichissement NHTSA si VIN disponible
        if data.get("vin"):
            nhtsa = await decode_vin(data["vin"])
            if nhtsa.is_complete():
                return nhtsa

        return VehicleInfo(
            make=data.get("make"),
            model=data.get("model"),
            year=str(data["year"]) if data.get("year") else None,
            engine=data.get("engine"),
            vin=data.get("vin"),
            confidence=float(data.get("confidence", 0.8)),
            source="ocr",
        )

    except Exception as exc:
        logger.error("Image VIN extraction failed: %s", exc)
        return VehicleInfo(confidence=0.0, source="ocr_failed")
