from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/autocommerce_embedding_tests.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=",
)
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from models.database import Base, Product, Store  # noqa: E402
from services import embedding_search  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self.store[key] = value
        return True


class FakeEmbeddingsAPI:
    def __init__(self, vector: list[float], call_counter: dict[str, int]) -> None:
        self.vector = vector
        self.call_counter = call_counter

    async def create(self, *, model: str, input: str):
        self.call_counter["count"] += 1
        return SimpleNamespace(data=[SimpleNamespace(embedding=self.vector)])


class FakeOpenAIClient:
    def __init__(self, vector: list[float], call_counter: dict[str, int]) -> None:
        self.embeddings = FakeEmbeddingsAPI(vector, call_counter)


class FakeMappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakePgSession:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.last_statement = None
        self.last_params = None

    async def execute(self, statement, params=None):
        self.last_statement = statement
        self.last_params = params
        return FakeMappingResult(self.rows)


@pytest.fixture()
def fake_vector() -> list[float]:
    return [0.001] * 1536


@pytest.fixture()
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.mark.asyncio
async def test_search_products_pgvector_returns_sorted_results(monkeypatch, fake_vector, fake_redis):
    call_counter = {"count": 0}
    rows = [
        {
            "id": 2,
            "name": "Produit A",
            "price": 10.5,
            "stock_qty": 4,
            "category": "Promo",
            "similarity_score": 0.97,
        },
        {
            "id": 5,
            "name": "Produit B",
            "price": 15.0,
            "stock_qty": 7,
            "category": "Accessoires",
            "similarity_score": 0.81,
        },
    ]
    db = FakePgSession(rows)

    async def fake_resolve_openai_client(store_id, _db):
        assert store_id == 42
        return FakeOpenAIClient(fake_vector, call_counter)

    monkeypatch.setattr(embedding_search, "resolve_openai_client", fake_resolve_openai_client)
    monkeypatch.setattr(embedding_search, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(embedding_search, "PGVECTOR_AVAILABLE", True)

    results = await embedding_search.search_products("promo été", 42, limit=2, db=db)

    assert [item["id"] for item in results] == [2, 5]
    assert results[0]["similarity_score"] == pytest.approx(0.97)
    assert results[1]["name"] == "Produit B"
    assert call_counter["count"] == 1
    assert ":vec" in str(db.last_statement)
    assert db.last_params["sid"] == 42
    assert db.last_params["limit"] == 2
    assert db.last_params["vec"].startswith("[")


@pytest.mark.asyncio
async def test_search_products_fallback_ilike_on_sqlite(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Store.__table__, Product.__table__])

    async with session_factory() as session:
        session.add(Store(id=1, name="Demo", slug="demo"))
        session.add_all(
            [
                Product(store_id=1, name="Chaussure running", description="Confort sport homme", price=99.0, stock_qty=3, category="Sport", is_active=True),
                Product(store_id=1, name="Veste hiver", description="Très chaude", price=120.0, stock_qty=2, category="Mode", is_active=True),
                Product(store_id=1, name="Sac sport", description="Idéal pour running", price=45.0, stock_qty=0, category="Sport", is_active=True),
            ]
        )
        await session.commit()

        monkeypatch.setattr(embedding_search, "PGVECTOR_AVAILABLE", False)
        monkeypatch.setattr(
            embedding_search,
            "embed_query",
            AsyncMock(return_value=[0.0] * 1536),
        )

        results = await embedding_search.search_products("running", 1, limit=10, db=session)

        assert len(results) == 1
        assert results[0]["name"] == "Chaussure running"
        assert results[0]["similarity_score"] == 1.0

    await engine.dispose()


@pytest.mark.asyncio
async def test_embed_query_uses_redis_cache(monkeypatch, fake_vector, fake_redis):
    call_counter = {"count": 0}

    async def fake_resolve_openai_client(store_id, _db):
        assert store_id == 7
        return FakeOpenAIClient(fake_vector, call_counter)

    monkeypatch.setattr(embedding_search, "resolve_openai_client", fake_resolve_openai_client)
    monkeypatch.setattr(embedding_search, "get_redis", lambda: fake_redis)

    first = await embedding_search.embed_query("même requête", 7, db=object())
    second = await embedding_search.embed_query("même requête", 7, db=object())

    assert len(first) == 1536
    assert first == second
    assert call_counter["count"] == 1
    assert len(fake_redis.store) == 1


@pytest.mark.asyncio
async def test_search_products_returns_empty_list_for_empty_store(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Store.__table__, Product.__table__])

    async with session_factory() as session:
        session.add(Store(id=9, name="Empty", slug="empty"))
        await session.commit()

        monkeypatch.setattr(embedding_search, "PGVECTOR_AVAILABLE", False)
        monkeypatch.setattr(
            embedding_search,
            "embed_query",
            AsyncMock(return_value=[0.0] * 1536),
        )

        results = await embedding_search.search_products("introuvable", 9, limit=5, db=session)

        assert results == []

    await engine.dispose()
