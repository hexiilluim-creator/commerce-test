from __future__ import annotations

from utils.llm_parser import parse_llm_json


def test_parse_llm_json_accepts_direct_object() -> None:
    assert parse_llm_json('{"status": "ok", "count": 2}') == {"status": "ok", "count": 2}



def test_parse_llm_json_extracts_markdown_code_block() -> None:
    raw = "Réponse:\n```json\n{\n  \"items\": [1, 2, 3]\n}\n```"

    assert parse_llm_json(raw) == {"items": [1, 2, 3]}



def test_parse_llm_json_extracts_first_array_from_preamble() -> None:
    raw = "Voici les données finales: [\"a\", \"b\", \"c\"] merci"

    assert parse_llm_json(raw) == ["a", "b", "c"]



def test_parse_llm_json_returns_none_on_invalid_json_fragment() -> None:
    raw = "```json\n{invalid json}\n```"

    assert parse_llm_json(raw) is None



def test_parse_llm_json_returns_none_on_empty_input() -> None:
    assert parse_llm_json("") is None
