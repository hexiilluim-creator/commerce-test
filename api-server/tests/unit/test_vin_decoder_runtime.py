from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services import vin_decoder


def test_vehicle_info_helpers_and_heuristics():
    complete = vin_decoder.VehicleInfo(make="Peugeot", model="206", year="2018", engine="1.6 HDi", confidence=0.9, source="heuristic")
    assert complete.is_complete() is True
    assert complete.summary() == "Peugeot 206 2018 1.6 HDi"
    assert complete.to_dict()["make"] == "Peugeot"
    assert vin_decoder.VehicleInfo(vin="VF3ABC12345678901").is_complete() is True
    assert vin_decoder._extract_vin("VIN VF3ABC12345678901") == "VF3ABC12345678901"
    assert vin_decoder._extract_make("Peugeot 206") == "Peugeot"
    assert vin_decoder._extract_year("modèle 2018") == "2018"
    assert vin_decoder._extract_year("modèle 2099") is None


@pytest.mark.asyncio
async def test_decode_vin_network_error_preserves_vin():
    with patch("httpx.AsyncClient", side_effect=RuntimeError("offline")):
        result = await vin_decoder.decode_vin(" vf3abc12345678901 ")
    assert result.vin == "VF3ABC12345678901"
    assert result.source == "nhtsa_failed"


@pytest.mark.asyncio
async def test_extract_from_text_uses_heuristics_for_vin():
    with patch("services.vin_decoder.decode_vin", new=AsyncMock(return_value=vin_decoder.VehicleInfo(vin="VF3ABC12345678901", make="Peugeot", source="nhtsa"))):
        result = await vin_decoder.extract_from_text("Peugeot, VIN VF3ABC12345678901")
    assert result.vin == "VF3ABC12345678901"


@pytest.mark.asyncio
async def test_decode_vin_success_builds_engine_and_metadata():
    response = SimpleNamespace(
        json=lambda: {"Results": [
            {"Variable": "Make", "Value": "Peugeot"},
            {"Variable": "Model", "Value": "208"},
            {"Variable": "Model Year", "Value": 2020},
            {"Variable": "Displacement (L)", "Value": "1.2"},
            {"Variable": "Fuel Type - Primary", "Value": "Gasoline"},
            {"Variable": "Unused", "Value": "Not Applicable"},
        ]},
        raise_for_status=lambda: None,
    )
    client = AsyncMock(); client.get = AsyncMock(return_value=response)
    client.__aenter__.return_value = client
    with patch("services.vin_decoder.httpx.AsyncClient", return_value=client):
        result = await vin_decoder.decode_vin("vf3abc12345678901")
    assert result.make == "Peugeot" and result.model == "208" and result.year == "2020"
    assert result.engine == "1.2L Gasoline" and result.confidence == 0.95


def test_vehicle_info_empty_summary_and_heuristic_aliases():
    empty = vin_decoder.VehicleInfo()
    assert empty.is_complete() is False and empty.summary() == "Véhicule inconnu"
    assert vin_decoder._extract_make("Mercedes Benz Clio") == "Mercedes"
    assert vin_decoder._extract_vin("invalid IOQ") is None
    assert vin_decoder._extract_year("année 1975") == "1975"


@pytest.mark.asyncio
async def test_extract_from_text_heuristic_make_model_year_without_vin():
    result = await vin_decoder.extract_from_text("Renault Clio modèle 2018, moteur 1.5 dci")
    assert result.make == "Renault" and result.year == "2018"
