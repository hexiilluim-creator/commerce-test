"""services/oem_lookup.py — Lookup de références OEM pièces automobiles.

Sources supportées (par ordre de priorité) :
  1. TecDoc REST API  (clé `tecdoc_api_key_enc` + `tecdoc_provider_id` sur Store).
  2. AutoISO API      (clé `autoiso_api_key_enc` sur Store).
  3. NHTSA Parts API  (gratuite, sans clé — résultats génériques).
  4. LLM fallback     (génère des références probables depuis la connaissance générale).

Interface publique :
  OemResult                            — dataclass de résultat
  lookup_oem_reference(make, model, year, part_query, ...) -> OemResult
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Timeouts ───────────────────────────────────────────────────────────────────
_HTTP_TIMEOUT = 10.0


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class OemResult:
    """Résultat d'un lookup OEM."""
    references: list[dict[str, str]] = field(default_factory=list)
    # Chaque ref : {"ref": "...", "brand": "...", "description": "..."}
    source:     str = "unknown"   # "tecdoc" | "autoiso" | "nhtsa" | "llm" | "none"
    warning:    str | None = None  # Message d'avertissement si données partielles

    def best_refs(self) -> list[str]:
        """Retourne les meilleures références OEM (max 5) pour la recherche en stock."""
        return [r["ref"] for r in self.references[:5] if r.get("ref")]

    def has_results(self) -> bool:
        return bool(self.references)


# ── TecDoc API ────────────────────────────────────────────────────────────────
# Documentation : https://webservice.tecalliance.services/pegasus-3-0/info

_TECDOC_BASE = "https://webservice.tecalliance.services/pegasus-3-0/services/TecdocToCatDLB.json"

async def _lookup_tecdoc(
    make: str,
    model: str,
    year: str,
    part_query: str,
    api_key: str,
    provider_id: str,
) -> OemResult:
    """Lookup via TecDoc REST API (partenaires certifiés uniquement)."""
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            # Étape 1 : obtenir l'ID véhicule TecDoc
            vehicle_resp = await client.post(
                f"{_TECDOC_BASE}/getVehiclesByIds",
                headers=headers,
                json={
                    "providerId": int(provider_id),
                    "articleCountry": "TN",
                    "lang": "fr",
                    "searchQuery": f"{make} {model} {year}",
                    "vehicleType": 1,
                },
            )
            vehicle_resp.raise_for_status()
            vehicles = vehicle_resp.json().get("array", [])

            if not vehicles:
                return OemResult(source="tecdoc", warning="Véhicule non trouvé dans TecDoc")

            vehicle_id = vehicles[0].get("carId")

            # Étape 2 : chercher les articles par véhicule + terme
            articles_resp = await client.post(
                f"{_TECDOC_BASE}/getArticles",
                headers=headers,
                json={
                    "providerId": int(provider_id),
                    "articleCountry": "TN",
                    "lang": "fr",
                    "carId": vehicle_id,
                    "searchQuery": part_query,
                    "perPage": 10,
                    "page": 1,
                },
            )
            articles_resp.raise_for_status()
            articles = articles_resp.json().get("articles", [])

            refs = []
            for art in articles[:8]:
                refs.append({
                    "ref": art.get("articleNumber", ""),
                    "brand": art.get("brandName", ""),
                    "description": art.get("genericArticle", {}).get("genericArticleDescription", part_query),
                })

            return OemResult(
                references=refs,
                source="tecdoc",
                warning=None if refs else "Aucune référence TecDoc pour cette pièce",
            )

    except httpx.HTTPStatusError as exc:
        logger.warning("TecDoc HTTP error %s: %s", exc.response.status_code, exc)
        return OemResult(source="tecdoc", warning=f"TecDoc indisponible (HTTP {exc.response.status_code})")
    except Exception as exc:
        logger.warning("TecDoc lookup failed: %s", exc)
        return OemResult(source="tecdoc", warning="TecDoc indisponible")


# ── AutoISO API ────────────────────────────────────────────────────────────────

_AUTOISO_BASE = "https://api.autoiso.com/v2"

async def _lookup_autoiso(
    make: str,
    model: str,
    year: str,
    part_query: str,
    api_key: str,
) -> OemResult:
    """Lookup via AutoISO API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{_AUTOISO_BASE}/parts/search",
                headers=headers,
                params={
                    "make": make,
                    "model": model,
                    "year": year,
                    "query": part_query,
                    "limit": 10,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            refs = []
            for part in data.get("parts", [])[:8]:
                refs.append({
                    "ref": part.get("oem_number", part.get("part_number", "")),
                    "brand": part.get("brand", ""),
                    "description": part.get("name", part_query),
                })

            return OemResult(
                references=refs,
                source="autoiso",
                warning=None if refs else "Aucune référence AutoISO",
            )
    except Exception as exc:
        logger.warning("AutoISO lookup failed: %s", exc)
        return OemResult(source="autoiso", warning="AutoISO indisponible")


# ── LLM Fallback ──────────────────────────────────────────────────────────────

_LLM_OEM_PROMPT = """Tu es un expert en pièces automobiles.
Génère les références OEM les plus probables pour cette demande.
Réponds UNIQUEMENT avec un JSON valide :
{
  "references": [
    {"ref": "XXXXX", "brand": "Marque équipementier", "description": "Description pièce"},
    ...
  ],
  "warning": "Message d'avertissement si données incertaines ou null"
}

Génère 3-5 références réalistes. Si tu n'es pas sûr, indique-le dans warning.
Marques équipementiers courants : Bosch, Valeo, NGK, Mann, Mahle, Brembo, TRW, SKF, Febi.
"""

async def _lookup_llm(
    make: str,
    model: str,
    year: str,
    part_query: str,
) -> OemResult:
    """Fallback LLM — génère des références probables depuis la connaissance générale.

    ⚠️ Ces références sont indicatives et doivent être vérifiées avant commande.
    """
    user_msg = f"Véhicule : {make} {model} {year}\nPièce recherchée : {part_query}"
    try:
        from services import llm_gateway
        r = await llm_gateway.chat(
            messages=[
                {"role": "system", "content": _LLM_OEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            agent_name="oem_lookup.llm_fallback",
            max_tokens=400,
            temperature=0.1,
        )
        raw = r.choices[0].message.content.strip().replace("```json", "").replace("```", "")
        data = json.loads(raw)

        refs = data.get("references", [])
        warning = data.get("warning") or "⚠️ Références générées par IA — à vérifier avant commande"

        return OemResult(
            references=refs[:5],
            source="llm",
            warning=warning,
        )
    except Exception as exc:
        logger.error("LLM OEM fallback failed: %s", exc)
        return OemResult(
            source="llm",
            warning="Impossible de générer des références OEM. Contactez votre fournisseur.",
        )


# ── Point d'entrée principal ──────────────────────────────────────────────────

async def lookup_oem_reference(
    make: str,
    model: str,
    year: str,
    part_query: str,
    *,
    tecdoc_api_key: str | None = None,
    tecdoc_provider_id: str | None = None,
    autoiso_api_key: str | None = None,
) -> OemResult:
    """Lookup OEM multi-source avec fallback automatique.

    Args:
        make               : Marque du véhicule (ex: "Peugeot").
        model              : Modèle (ex: "206").
        year               : Année (ex: "2008").
        part_query         : Pièce recherchée (ex: "filtre huile").
        tecdoc_api_key     : Clé API TecDoc (optionnel).
        tecdoc_provider_id : ID Provider TecDoc (optionnel).
        autoiso_api_key    : Clé API AutoISO (optionnel).

    Returns:
        OemResult avec les références trouvées et la source utilisée.
    """
    # 1. TecDoc (prioritaire si configuré)
    if tecdoc_api_key and tecdoc_provider_id:
        result = await _lookup_tecdoc(
            make, model, year, part_query,
            tecdoc_api_key, tecdoc_provider_id,
        )
        if result.has_results():
            logger.info(
                "OEM lookup TecDoc: %d refs for %s %s %s / %s",
                len(result.references), make, model, year, part_query,
            )
            return result
        logger.debug("TecDoc no results, trying next source")

    # 2. AutoISO
    if autoiso_api_key:
        result = await _lookup_autoiso(make, model, year, part_query, autoiso_api_key)
        if result.has_results():
            logger.info(
                "OEM lookup AutoISO: %d refs for %s %s %s / %s",
                len(result.references), make, model, year, part_query,
            )
            return result
        logger.debug("AutoISO no results, falling back to LLM")

    # 3. LLM fallback (toujours disponible)
    logger.info("OEM lookup LLM fallback for %s %s %s / %s", make, model, year, part_query)
    return await _lookup_llm(make, model, year, part_query)
