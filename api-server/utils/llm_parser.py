"""utils/llm_parser.py — JSON extraction from LLM responses."""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_llm_json(text: str) -> dict | list | None:
    """Extract and parse the first valid JSON object or array from an LLM response.

    LLMs sometimes wrap JSON in markdown code blocks (```json ... ```) or add
    preamble text before the JSON. This function handles all common cases.
    """
    if not text:
        return None

    # 1. Try direct parse first (fastest, covers clean responses)
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Try to extract from markdown code block
    md_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
    if md_match:
        try:
            return json.loads(md_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Try to find first {...} or [...] block
    brace_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", stripped)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("parse_llm_json: could not extract JSON from: %.200s", text)
    return None
