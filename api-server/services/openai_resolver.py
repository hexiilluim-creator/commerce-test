"""services/openai_resolver.py — résolution centralisée du client OpenAI."""
from __future__ import annotations

from openai import AsyncOpenAI

from config import settings


def get_platform_client() -> AsyncOpenAI:
    """Retourne le client plateforme par défaut."""
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def resolve_openai_client(store_id: int, db) -> AsyncOpenAI:
    """Résout le client OpenAI pour un tenant.

    La version BYOK complète n'est pas matérialisée dans cette archive ;
    on retourne le client plateforme par défaut pour les services qui en ont besoin.
    """
    return get_platform_client()
