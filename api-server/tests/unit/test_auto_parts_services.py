"""tests/test_auto_parts_services.py — Tests unitaires pour les 4 services pièces auto.

Couvre :
  - vin_decoder  : extraction texte, heuristiques, VehicleInfo
  - oem_lookup   : OemResult, best_refs, LLM fallback mocké
  - stock_resolver : StockItem, format_wa, resolve_stock avec DB mockée
  - voice_transcriber : cache, detect_language_hint, download + transcribe
"""
from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# VIN DECODER
# ═══════════════════════════════════════════════════════════════════════════════
from services.vin_decoder import (
    VehicleInfo,
    _extract_make,
    _extract_vin,
    _extract_year,
    decode_vin,
    extract_from_text,
)


class TestVehicleInfo:
    def test_is_complete_with_make_and_year(self):
        v = VehicleInfo(make="Peugeot", year="2018")
        assert v.is_complete() is True

    def test_is_complete_with_vin(self):
        v = VehicleInfo(vin="WBA3A5C50DF000001")
        assert v.is_complete() is True

    def test_not_complete_empty(self):
        v = VehicleInfo()
        assert v.is_complete() is False

    def test_not_complete_make_only(self):
        v = VehicleInfo(make="Renault")
        assert v.is_complete() is False

    def test_summary_full(self):
        v = VehicleInfo(make="Peugeot", model="206", year="2008", engine="1.4 HDi")
        assert v.summary() == "Peugeot 206 2008 1.4 HDi"

    def test_summary_empty(self):
        v = VehicleInfo()
        assert v.summary() == "Véhicule inconnu"

    def test_to_dict(self):
        v = VehicleInfo(make="Renault", year="2015")
        d = v.to_dict()
        assert d["make"] == "Renault"
        assert d["year"] == "2015"


class TestVinHeuristics:
    def test_extract_year_valid(self):
        assert _extract_year("clio 2015 essence") == "2015"
        assert _extract_year("2008 206 diesel") == "2008"
        assert _extract_year("no year here") is None

    def test_extract_year_range(self):
        assert _extract_year("1969") is None   # avant 1970
        assert _extract_year("2031") is None   # trop loin

    def test_extract_make_fr(self):
        assert _extract_make("filtre pour clio") == "Renault"
        assert _extract_make("206 essence") == "Peugeot"
        assert _extract_make("batterie bmw") == "BMW"
        assert _extract_make("voiture quelconque") is None

    def test_extract_make_alias(self):
        assert _extract_make("merco e200") == "Mercedes"
        assert _extract_make("pejo 308 2019") == "Peugeot"

    def test_extract_vin_valid(self):
        vin = "WBA3A5C50DF000001"
        assert _extract_vin(f"mon chassis {vin} ok") == vin

    def test_extract_vin_invalid_length(self):
        assert _extract_vin("12345") is None

    def test_extract_vin_invalid_chars(self):
        # VIN ne peut pas contenir I, O, Q
        assert _extract_vin("WBAIAAAAAAAAA0001") is None


@pytest.mark.asyncio
async def test_extract_from_text_heuristic():
    """Test extraction avec heuristiques (sans appel LLM)."""
    result = await extract_from_text("Renault Clio 2018")
    assert result.make == "Renault"
    assert result.year == "2018"
    assert result.source in ("heuristic", "llm")


@pytest.mark.asyncio
async def test_extract_from_text_empty():
    result = await extract_from_text("")
    assert result.is_complete() is False


@pytest.mark.asyncio
async def test_decode_vin_network_failure():
    """Vérifie le fallback si NHTSA est down."""
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception("network down")
        )
        result = await decode_vin("WBA3A5C50DF000001")
        assert result.vin == "WBA3A5C50DF000001"
        assert result.source == "nhtsa_failed"


# ═══════════════════════════════════════════════════════════════════════════════
# OEM LOOKUP
# ═══════════════════════════════════════════════════════════════════════════════

from services.oem_lookup import OemResult, lookup_oem_reference


class TestOemResult:
    def test_best_refs_limit(self):
        refs = [{"ref": f"REF{i}", "brand": "Bosch"} for i in range(10)]
        r = OemResult(references=refs)
        assert len(r.best_refs()) == 5

    def test_best_refs_empty(self):
        r = OemResult()
        assert r.best_refs() == []

    def test_has_results(self):
        r = OemResult(references=[{"ref": "123", "brand": "NGK"}])
        assert r.has_results() is True
        assert OemResult().has_results() is False


@pytest.mark.asyncio
async def test_lookup_oem_llm_fallback():
    """Sans clés TecDoc/AutoISO, doit utiliser le fallback LLM."""
    fake_llm_response = json.dumps({
        "references": [
            {"ref": "7700274176", "brand": "Renault", "description": "Filtre à huile"},
            {"ref": "8200768927", "brand": "Bosch", "description": "Filtre huile"},
        ],
        "warning": "Références indicatives"
    })

    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = fake_llm_response

    with patch("services.llm_gateway.chat", new=AsyncMock(return_value=mock_completion)):
        result = await lookup_oem_reference(
            make="Renault", model="Clio", year="2015",
            part_query="filtre huile",
        )

    assert result.source == "llm"
    assert len(result.references) == 2
    assert result.references[0]["ref"] == "7700274176"
    assert result.warning == "Références indicatives"


@pytest.mark.asyncio
async def test_lookup_oem_no_keys_no_crash():
    """Vérifie que l'absence de toutes les clés ne lève pas d'exception."""
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = '{"references": [], "warning": "aucun résultat"}'

    with patch("services.llm_gateway.chat", new=AsyncMock(return_value=mock_completion)):
        result = await lookup_oem_reference(
            "Peugeot", "206", "2008", "amortisseur avant"
        )
    assert isinstance(result, OemResult)


# ═══════════════════════════════════════════════════════════════════════════════
# STOCK RESOLVER
# ═══════════════════════════════════════════════════════════════════════════════

from services.stock_resolver import StockItem, resolve_stock


class TestStockItem:
    def test_is_in_stock(self):
        assert StockItem("Filtre", "REF1", 25.0, 3).is_in_stock() is True
        assert StockItem("Filtre", "REF1", 25.0, 0).is_in_stock() is False

    def test_format_wa_in_stock(self):
        item = StockItem("Filtre à huile", "BOC1234", 12.500, 5)
        msg = item.format_wa()
        assert "Filtre à huile" in msg
        assert "12.500" in msg
        assert "✅" in msg
        assert "BOC1234" in msg

    def test_format_wa_out_of_stock(self):
        item = StockItem("Plaquettes", None, 45.0, 0)
        msg = item.format_wa()
        assert "⚠️" in msg
        assert "45.000" in msg

    def test_format_wa_no_reference(self):
        item = StockItem("Courroie", None, 30.0, 2)
        msg = item.format_wa()
        assert "Courroie" in msg
        # Pas de backtick si pas de référence
        assert "`None`" not in msg


@pytest.mark.asyncio
async def test_resolve_stock_returns_list():
    """Vérifie que resolve_stock retourne toujours une liste même si DB vide."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

    mock_store = MagicMock()
    mock_store.id = 1
    mock_store.stock_api_url = None

    result = await resolve_stock(
        mock_db, mock_store,
        oem_refs=["REF123"],
        part_kws=["filtre", "huile"],
        vehicle_kws=["Renault", "Clio"],
    )
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_resolve_stock_deduplication():
    """Vérifie la déduplication entre local et externe."""
    from unittest.mock import patch

    item_local    = StockItem("Filtre", "REF-A", 20.0, 5, source="local")
    item_external = StockItem("Filtre copy", "REF-A", 22.0, 3, source="external")

    with patch("services.stock_resolver._search_local_stock", new=AsyncMock(return_value=[item_local])), \
         patch("services.stock_resolver._search_external_stock", new=AsyncMock(return_value=[item_external])):

        mock_db    = AsyncMock()
        mock_store = MagicMock()
        mock_store.id = 1
        mock_store.stock_api_url = "http://api.test"

        result = await resolve_stock(mock_db, mock_store, ["REF-A"], ["filtre"], [])
        # REF-A ne doit apparaître qu'une fois
        refs = [i.reference for i in result]
        assert refs.count("REF-A") == 1


# ═══════════════════════════════════════════════════════════════════════════════
# VOICE TRANSCRIBER
# ═══════════════════════════════════════════════════════════════════════════════

from services.voice_transcriber import (
    _transcribe_bytes,
    detect_language_hint,
    transcribe_whatsapp_audio,
)


class TestDetectLanguageHint:
    def test_arabic_text(self):
        assert detect_language_hint("أريد قطعة غيار للسيارة") == "ar"

    def test_french_text(self):
        assert detect_language_hint("je voudrais un filtre bonjour merci") == "fr"

    def test_unknown(self):
        assert detect_language_hint("hello world ok") is None

    def test_empty(self):
        assert detect_language_hint("") is None

    def test_mixed_arabic_dominant(self):
        # > 30% caractères arabes
        assert detect_language_hint("يريد filtre زيت") == "ar"


@pytest.mark.asyncio
async def test_transcribe_bytes_no_openai_key(monkeypatch):
    """Sans clé OpenAI, retourne chaîne vide sans lever d'exception."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = await _transcribe_bytes(b"fake audio bytes")
    assert result == ""


@pytest.mark.asyncio
async def test_transcribe_whatsapp_audio_cache_hit():
    """Si le cache Redis contient déjà la transcription, pas d'appel réseau."""
    with patch("services.voice_transcriber._cache_get", new=AsyncMock(return_value="bonjour monde")), \
         patch("services.voice_transcriber._download_media", new=AsyncMock()) as mock_dl:
        result = await transcribe_whatsapp_audio("media_abc123")
        assert result == "bonjour monde"
        mock_dl.assert_not_called()


@pytest.mark.asyncio
async def test_transcribe_whatsapp_audio_download_failure():
    """Si le téléchargement échoue, retourne chaîne vide sans lever d'exception."""
    with patch("services.voice_transcriber._cache_get", new=AsyncMock(return_value=None)), \
         patch("services.voice_transcriber._download_media", new=AsyncMock(side_effect=Exception("network error"))):
        result = await transcribe_whatsapp_audio("media_bad")
        assert result == ""


@pytest.mark.asyncio
async def test_transcribe_whatsapp_audio_full_pipeline():
    """Test du pipeline complet : download -> whisper -> cache."""
    fake_audio = b"\x00\x01\x02\x03"
    fake_text  = "filtre huile renault"

    with patch("services.voice_transcriber._cache_get", new=AsyncMock(return_value=None)), \
         patch("services.voice_transcriber._download_media", new=AsyncMock(return_value=fake_audio)), \
         patch("services.voice_transcriber._transcribe_bytes", new=AsyncMock(return_value=fake_text)), \
         patch("services.voice_transcriber._cache_set", new=AsyncMock()) as mock_cache_set:

        result = await transcribe_whatsapp_audio("media_ok", mime_type="audio/ogg")
        assert result == fake_text
        mock_cache_set.assert_called_once_with("whisper:transcript:media_ok", fake_text)
