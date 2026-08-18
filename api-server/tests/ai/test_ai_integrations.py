"""tests/ai/test_ai_integrations.py — services/llm_gateway.py (chat routing,
circuit breaker, budget/quota, fallback DeepSeek -> OpenAI).

V28-FIXED-P1 : réécriture complète. L'ancienne version mockait des attributs
qui n'existent pas dans le module réel (``services.llm_gateway.DeepSeek`` /
``.OpenAI``), patchait ``config.settings`` alors que ``llm_gateway.py`` fait
``from config import settings`` (une copie locale, insensible au patch sur le
module ``config``), supposait des clés Redis et des messages d'exception qui
ne correspondent pas à l'implémentation, et traitait ``_CircuitBreaker.is_open()``
comme une coroutine alors qu'elle est synchrone. Résultat : 10 erreurs / 2
échecs sur 12 tests, confirmés à l'exécution.

Cette version mocke :
  - ``services.llm_gateway.settings``  (le binding réellement utilisé)
  - ``services.llm_gateway._get_redis`` (quota/budget — utilisé par _check_budget
    et _record_usage)
  - ``lib.redis_client.get_redis``      (circuit breaker — _CircuitBreaker._get_redis
    importe ce nom localement à chaque appel)
  - ``openai.AsyncOpenAI``              (le SDK réel utilisé par _call_deepseek
    ET _call_openai — différencié par le kwarg ``base_url`` présent uniquement
    côté DeepSeek)

avec un faux Redis fonctionnel en mémoire (get/set/incr/pipeline) plutôt que
des retours programmés à la main, pour rester fidèle au comportement réel
même sur des scénarios multi-appels (ouverture puis fermeture du circuit).
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import llm_gateway
from services.llm_gateway import (
    AllProvidersFailedError,
    BudgetExceededError,
    _CircuitBreaker,
    chat,
)


# ──────────────────────────────────────────────────────────────────────────
# Faux Redis async, fonctionnel en mémoire (get/set/incr/pipeline)
# ──────────────────────────────────────────────────────────────────────────
class _FakePipeline:
    def __init__(self, store: dict):
        self._store = store
        self._ops: list[tuple[str, tuple, dict]] = []

    def _queue(self, name, *args, **kwargs):
        self._ops.append((name, args, kwargs))
        return self

    def set(self, key, value, **kw):
        return self._queue("set", key, value, **kw)

    def incr(self, key, amount=1):
        return self._queue("incr", key, amount)

    def incrby(self, key, amount):
        return self._queue("incrby", key, amount)

    def incrbyfloat(self, key, amount):
        return self._queue("incrbyfloat", key, amount)

    def delete(self, key):
        return self._queue("delete", key)

    def expire(self, key, seconds):
        return self._queue("expire", key, seconds)

    async def execute(self):
        results = []
        for name, args, kwargs in self._ops:
            key = args[0]
            if name == "set":
                self._store[key] = args[1]
                results.append(True)
            elif name in ("incr", "incrby"):
                amount = args[1] if len(args) > 1 else 1
                cur = int(self._store.get(key, 0) or 0) + amount
                self._store[key] = str(cur)
                results.append(cur)
            elif name == "incrbyfloat":
                cur = float(self._store.get(key, 0) or 0) + args[1]
                self._store[key] = str(cur)
                results.append(cur)
            elif name == "delete":
                self._store.pop(key, None)
                results.append(1)
            elif name == "expire":
                results.append(True)
        self._ops.clear()
        return results


class FakeAsyncRedis:
    """Redis async minimal, en mémoire, suffisant pour llm_gateway."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.ping_fails = False

    async def ping(self):
        if self.ping_fails:
            raise ConnectionError("redis down")
        return True

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return 1

    def pipeline(self):
        return _FakePipeline(self.store)


def _fake_openai_response(content: str, prompt_tokens=10, completion_tokens=20, id_="mock-id"):
    """Mime la forme d'une réponse SDK openai (pas notre ChatCompletion interne)."""
    message = SimpleNamespace(role="assistant", content=content)
    choice = SimpleNamespace(index=0, message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(id=id_, choices=[choice], usage=usage)


class _FakeProviderClient:
    """Simule un client AsyncOpenAI (utilisé pour DeepSeek et OpenAI)."""

    def __init__(self, response=None, error: Exception | None = None):
        create = AsyncMock()
        if error is not None:
            create.side_effect = error
        else:
            create.return_value = response or _fake_openai_response("default reply")
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def default_settings(monkeypatch):
    """Réglages par défaut sur le binding réellement utilisé par le module :
    services.llm_gateway.settings (pas config.settings — copie séparée)."""
    monkeypatch.setattr(llm_gateway.settings, "FEATURE_FLAG_DEEPSEEK", True, raising=False)
    monkeypatch.setattr(llm_gateway.settings, "FEATURE_FLAG_OPENAI_FALLBACK", True, raising=False)
    monkeypatch.setattr(llm_gateway.settings, "DEEPSEEK_API_KEY", "test-deepseek-key", raising=False)
    monkeypatch.setattr(llm_gateway.settings, "OPENAI_API_KEY", "test-openai-key", raising=False)
    monkeypatch.setattr(llm_gateway.settings, "OPENAI_MODEL", "gpt-4o-mini", raising=False)
    monkeypatch.setattr(llm_gateway.settings, "AI_BUDGET_HARD_LIMIT_USD", 250.0, raising=False)
    monkeypatch.setattr(llm_gateway.settings, "AI_MAX_MONTHLY_CALLS", 10_000, raising=False)
    monkeypatch.setattr(llm_gateway.settings, "CB_OPENAI_THRESHOLD", 3, raising=False)
    monkeypatch.setattr(llm_gateway.settings, "CB_OPENAI_COOLDOWN", 60, raising=False)
    # Circuits neufs et fermés à chaque test (évite les fuites d'état entre tests)
    llm_gateway._cb_deepseek._failures = 0
    llm_gateway._cb_deepseek._opened_at = None
    llm_gateway._cb_openai._failures = 0
    llm_gateway._cb_openai._opened_at = None
    yield


@pytest.fixture
def fake_redis():
    """Faux Redis partagé, branché à la fois sur le chemin quota/budget
    (services.llm_gateway._get_redis) et sur le circuit breaker
    (lib.redis_client.get_redis)."""
    redis = FakeAsyncRedis()
    with patch("services.llm_gateway._get_redis", new=AsyncMock(return_value=redis)), \
         patch("lib.redis_client.get_redis", new=AsyncMock(return_value=redis)):
        yield redis


@pytest.fixture
def no_redis():
    """Simule une indisponibilité totale de Redis (fail-open attendu)."""
    with patch("services.llm_gateway._get_redis", new=AsyncMock(return_value=None)), \
         patch("lib.redis_client.get_redis", new=AsyncMock(side_effect=ConnectionError("down"))):
        yield


@pytest.fixture
def mock_providers(fake_redis):
    """Patch openai.AsyncOpenAI : différencie DeepSeek/OpenAI via le kwarg
    base_url (seul _call_deepseek le passe explicitement)."""
    deepseek_client = _FakeProviderClient(response=_fake_openai_response("DeepSeek response"))
    openai_client = _FakeProviderClient(response=_fake_openai_response("OpenAI response"))

    def _side_effect(*args, **kwargs):
        return deepseek_client if "base_url" in kwargs else openai_client

    with patch("openai.AsyncOpenAI", side_effect=_side_effect) as ctor:
        yield SimpleNamespace(ctor=ctor, deepseek=deepseek_client, openai=openai_client)


# ──────────────────────────────────────────────────────────────────────────
# chat() — routage DeepSeek primaire / fallback OpenAI
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_chat_deepseek_success(mock_providers):
    response = await chat(messages=[{"role": "user", "content": "Hello"}], tenant_id=1)
    assert response.content == "DeepSeek response"
    assert response.provider == "deepseek"
    mock_providers.deepseek.chat.completions.create.assert_called_once()
    mock_providers.openai.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_chat_deepseek_failure_fallback_openai_success(mock_providers):
    mock_providers.deepseek.chat.completions.create.side_effect = Exception("DeepSeek error")
    response = await chat(messages=[{"role": "user", "content": "Hello"}], tenant_id=1)
    assert response.content == "OpenAI response"
    assert response.provider == "openai"
    mock_providers.deepseek.chat.completions.create.assert_called_once()
    mock_providers.openai.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_chat_no_deepseek_api_key_fallback_openai(mock_providers, monkeypatch):
    monkeypatch.setattr(llm_gateway.settings, "DEEPSEEK_API_KEY", "", raising=False)
    response = await chat(messages=[{"role": "user", "content": "Hello"}], tenant_id=1)
    assert response.provider == "openai"
    mock_providers.deepseek.chat.completions.create.assert_not_called()
    mock_providers.openai.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_chat_no_provider_available_raises(mock_providers, monkeypatch):
    monkeypatch.setattr(llm_gateway.settings, "DEEPSEEK_API_KEY", "", raising=False)
    monkeypatch.setattr(llm_gateway.settings, "OPENAI_API_KEY", "", raising=False)
    with pytest.raises(AllProvidersFailedError, match="OPENAI_API_KEY non configuré"):
        await chat(messages=[{"role": "user", "content": "Hello"}], tenant_id=1)


@pytest.mark.asyncio
async def test_chat_system_message_injected(mock_providers):
    await chat(
        messages=[{"role": "user", "content": "What is your name?"}],
        system="You are a helpful assistant.",
        tenant_id=1,
    )
    _, kwargs = mock_providers.deepseek.chat.completions.create.call_args
    assert kwargs["messages"][0] == {"role": "system", "content": "You are a helpful assistant."}
    assert kwargs["messages"][1] == {"role": "user", "content": "What is your name?"}


@pytest.mark.asyncio
async def test_chat_redis_down_still_succeeds(mock_providers, no_redis):
    """Le budget check et le tracking d'usage sont non-bloquants : Redis down
    ne doit jamais empêcher une réponse LLM de partir (fail-open volontaire)."""
    response = await chat(messages=[{"role": "user", "content": "Hello"}], tenant_id=1)
    assert response.provider == "deepseek"


# ──────────────────────────────────────────────────────────────────────────
# Budget / quota (Redis réel simulé)
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_chat_budget_exceeded(mock_providers, fake_redis, monkeypatch):
    monkeypatch.setattr(llm_gateway.settings, "AI_BUDGET_HARD_LIMIT_USD", 10.0, raising=False)
    fake_redis.store[llm_gateway._month_key("llm:cost_usd")] = "15.0"
    with pytest.raises(BudgetExceededError, match="Budget mensuel IA dépassé"):
        await chat(messages=[{"role": "user", "content": "Hello"}], tenant_id=1)
    mock_providers.deepseek.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_chat_calls_quota_exceeded(mock_providers, fake_redis, monkeypatch):
    monkeypatch.setattr(llm_gateway.settings, "AI_MAX_MONTHLY_CALLS", 5, raising=False)
    fake_redis.store[llm_gateway._month_key("llm:calls")] = "5"
    with pytest.raises(BudgetExceededError, match="Quota mensuel appels IA dépassé"):
        await chat(messages=[{"role": "user", "content": "Hello"}], tenant_id=1)


@pytest.mark.asyncio
async def test_chat_records_usage_platform_and_store(mock_providers, fake_redis):
    await chat(messages=[{"role": "user", "content": "Hello"}], tenant_id=42)
    assert float(fake_redis.store[llm_gateway._month_key("llm:cost_usd")]) > 0
    assert int(fake_redis.store[llm_gateway._month_key("llm:calls")]) == 1
    assert float(fake_redis.store[llm_gateway._month_key("llm:cost_usd", 42)]) > 0
    assert int(fake_redis.store[llm_gateway._month_key("llm:calls", 42)]) == 1


@pytest.mark.asyncio
async def test_chat_no_tenant_id_still_records_platform_usage(mock_providers, fake_redis):
    """Sans tenant_id, seuls les compteurs par store sont sautés — les
    compteurs plateforme sont toujours écrits (comportement réel, pas de
    tracking conditionnel côté plateforme)."""
    await chat(messages=[{"role": "user", "content": "Hello"}])
    assert int(fake_redis.store[llm_gateway._month_key("llm:calls")]) == 1


# ──────────────────────────────────────────────────────────────────────────
# _CircuitBreaker — Redis-backed, fallback in-memory
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_circuit_breaker_record_failure_opens_after_threshold(fake_redis):
    cb = _CircuitBreaker(name="test_cb", threshold=3, cooldown_seconds=60)
    for _ in range(2):
        await cb.record_failure()
        assert cb.is_open() is False  # sous le seuil : toujours fermé
    await cb.record_failure()  # 3e échec : atteint le seuil
    assert cb.is_open() is True
    assert fake_redis.store[cb._redis_state_key] == "open"


@pytest.mark.asyncio
async def test_circuit_breaker_record_success_resets(fake_redis):
    cb = _CircuitBreaker(name="test_cb", threshold=2, cooldown_seconds=60)
    await cb.record_failure()
    await cb.record_failure()
    assert cb.is_open() is True
    await cb.record_success()
    assert cb.is_open() is False
    assert fake_redis.store.get(cb._redis_state_key) == "closed"
    assert cb._redis_failures_key not in fake_redis.store
    assert cb._redis_opened_key not in fake_redis.store


def test_circuit_breaker_is_open_is_sync_and_respects_cooldown():
    """is_open() est synchrone (pas une coroutine) — vérification directe
    de l'état in-memory local, sans appel réseau."""
    cb = _CircuitBreaker(name="cooldown_cb", threshold=1, cooldown_seconds=0)
    assert cb.is_open() is False
    cb._opened_at = time.monotonic() - 1  # cooldown déjà écoulé (0s configuré)
    assert cb.is_open() is False  # doit s'auto-refermer après le cooldown
    cb._opened_at = time.monotonic()
    cb._cooldown = 3600
    assert cb.is_open() is True  # cooldown pas écoulé


@pytest.mark.asyncio
async def test_circuit_breaker_open_skips_deepseek_falls_back_to_openai(mock_providers, fake_redis):
    llm_gateway._cb_deepseek._opened_at = time.monotonic()
    llm_gateway._cb_deepseek._failures = 999
    response = await chat(messages=[{"role": "user", "content": "Hello"}], tenant_id=1)
    assert response.provider == "openai"
    mock_providers.deepseek.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_circuit_breaker_redis_down_falls_back_to_in_memory(no_redis):
    """Si Redis est down, le circuit breaker doit continuer à fonctionner
    en mémoire (pas de régression — comportement documenté dans le docstring
    de _CircuitBreaker)."""
    cb = _CircuitBreaker(name="in_memory_cb", threshold=2, cooldown_seconds=60)
    await cb.record_failure()
    await cb.record_failure()
    assert cb.is_open() is True
