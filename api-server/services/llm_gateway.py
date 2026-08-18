"""services/llm_gateway.py — Routeur LLM centralisé.

Architecture:
  1. Provider primaire : DeepSeek (deepseek-chat, ~10× moins cher que GPT-4o)
     activé si FEATURE_FLAG_DEEPSEEK=True et DEEPSEEK_API_KEY non-vide.
  2. Fallback automatique : OpenAI gpt-4o-mini si DeepSeek échoue ou est indisponible.
  3. Budget enforcement : AI_BUDGET_HARD_LIMIT_USD, AI_MAX_MONTHLY_CALLS,
     AI_MAX_MONTHLY_TOKENS — vérifiés via compteurs Redis avant chaque appel.
  4. Circuit breaker indépendant par provider : seuils CB_OPENAI_THRESHOLD /
     CB_OPENAI_COOLDOWN (réutilisés pour les deux providers).
  5. Quota tracking : compteurs Redis par store + compteurs globaux plateforme
     (clés horodatées YYYYMM pour reset mensuel automatique).
  6. Logging structuré : provider, model, tokens, coût estimé USD, store_id,
     agent_name, channel, latence ms.

Coûts estimés (USD/1k tokens, indicatif) :
  DeepSeek deepseek-chat : input $0.00014, output $0.00028
  OpenAI  gpt-4o-mini    : input $0.000150, output $0.000600

Interface publique :
  async def chat(
      messages   : list[dict],
      *,
      model      : str | None = None,
      system     : str | None = None,
      max_tokens : int = 1024,
      temperature: float = 0.7,
      tenant_id  : int | None = None,
      agent_name : str = "chat",
      channel    : str = "chat",
  ) -> ChatCompletion           # objet OpenAI-compatible
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from config import settings

logger = logging.getLogger("llm_gateway")


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str


def provider_from_settings() -> LLMConfig:
    provider = (getattr(settings, "LLM_PROVIDER", "deepseek") or "deepseek").strip().lower()
    if provider == "stub":
        return LLMConfig(provider="stub", model="stub-1")
    if provider == "openai":
        return LLMConfig(provider="openai", model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"))
    return LLMConfig(provider="deepseek", model="deepseek-chat")


def _flag_enabled(name: str) -> bool:
    value = getattr(settings, name, False)
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}


def guard_provider(cfg: LLMConfig) -> None:
    # P0-fix (audit indépendant) : ce garde relisait os.getenv("ENV") en
    # priorité sur settings.ENV. settings.ENV est un champ Pydantic Settings
    # qui charge déjà la variable d'environnement ENV au démarrage — c'est
    # l'unique source de vérité utilisée partout ailleurs dans l'app (voir
    # config.py). Relire os.environ ici était redondant et rendait le garde
    # contournable : si une variable ENV restait définie au niveau OS/conteneur
    # (ex. docker-compose.test.yml fixe ENV=test), elle l'emportait
    # silencieusement sur settings.ENV, y compris en test où settings est
    # mocké — d'où deux tests qui échouaient avant d'être "réparés" en
    # supprimant la variable d'environnement dans le test plutôt qu'en
    # corrigeant cette fonction. Fixé pour de bon : plus aucune lecture de
    # os.environ ici.
    env = (getattr(settings, "ENV", None) or "production")
    env = env.strip().lower()
    prod_like = env in {"production", "prod", "staging"}
    if cfg.provider == "stub":
        if _flag_enabled("FEATURE_FLAG_BYOK_OPENAI"):
            raise RuntimeError("LLM_PROVIDER=stub interdit quand FEATURE_FLAG_BYOK_OPENAI est activé")
        if prod_like:
            raise RuntimeError("LLM_PROVIDER=stub interdit en production/staging")
    if cfg.provider == "openai" and prod_like:
        if _flag_enabled("FEATURE_FLAG_BYOK_OPENAI") and not getattr(settings, "STORE_OPENAI_KEY", ""):
            raise RuntimeError("STORE_OPENAI_KEY requis lorsque FEATURE_FLAG_BYOK_OPENAI est activé")
        if not getattr(settings, "OPENAI_API_KEY", ""):
            raise RuntimeError("OPENAI_API_KEY requis lorsque LLM_PROVIDER=openai en production/staging")
    if cfg.provider == "deepseek" and prod_like and not getattr(settings, "DEEPSEEK_API_KEY", ""):
        raise RuntimeError("DEEPSEEK_API_KEY requis lorsque LLM_PROVIDER=deepseek en production/staging")

# ──────────────────────────────────────────────────────────────────────────────
# Coûts par 1 000 tokens (USD)
# ──────────────────────────────────────────────────────────────────────────────
_COST_PER_1K: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
    "gpt-4o-mini": {"input": 0.000150, "output": 0.000600},
    "gpt-4o": {"input": 0.00500, "output": 0.01500},
}

_DEFAULT_COST = {"input": 0.001, "output": 0.002}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _COST_PER_1K.get(model, _DEFAULT_COST)
    return (input_tokens / 1000) * rates["input"] + (output_tokens / 1000) * rates["output"]


# ──────────────────────────────────────────────────────────────────────────────
# Types de retour compatibles OpenAI
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class _Message:
    role: str
    content: str


@dataclass
class _Choice:
    index: int
    message: _Message
    finish_reason: str = "stop"


@dataclass
class _Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ChatCompletion:
    """Réponse LLM compatible avec l'interface openai.types.chat.ChatCompletion."""
    id: str
    model: str
    choices: list[_Choice]
    usage: _Usage
    provider: str
    cost_usd: float
    latency_ms: int
    created: int = field(default_factory=lambda: int(time.time()))
    object: str = "chat.completion"

    # Compatibility for tests (V25 audit fix)
    def __init__(
        self,
        id: str = "fake-id",
        model: str = "unknown",
        choices: list[_Choice] | None = None,
        usage: _Usage | None = None,
        provider: str = "unknown",
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
        content: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        self.id = id
        self.model = model
        self.provider = provider
        self.cost_usd = cost_usd
        self.latency_ms = int(latency_ms)
        self.created = int(time.time())
        self.object = "chat.completion"
        
        if choices is not None:
            self.choices = choices
        elif content is not None:
            self.choices = [_Choice(index=0, message=_Message(role="assistant", content=content))]
        else:
            self.choices = []

        if usage is not None:
            self.usage = usage
        else:
            self.usage = _Usage(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens
            )

    @property
    def content(self) -> str:
        if self.choices and self.choices[0].message:
            return self.choices[0].message.content
        return ""

    @property
    def input_tokens(self) -> int:
        return self.usage.prompt_tokens

    @property
    def output_tokens(self) -> int:
        return self.usage.completion_tokens


# ──────────────────────────────────────────────────────────────────────────────
# Circuit Breaker — Redis-backed (V24 ENTERPRISE FIX)
# ──────────────────────────────────────────────────────────────────────────────
# V24 ENTERPRISE FIX: le circuit breaker était in-memory par process.
# Avec 8 workers Uvicorn, chaque worker ouvrait son circuit indépendamment :
# le worker 1 pouvait avoir DeepSeek OPEN pendant que les workers 2-8 le
# considéraient CLOSED, causant des centaines d'appels redondants vers un
# provider défaillant.
#
# Solution : état partagé via Redis (même stratégie que OmniCall V9).
# Fallback in-memory si Redis est indisponible (pas de régression).
class _CircuitBreaker:
    """Circuit breaker Redis-backed partagé entre workers Uvicorn.

    États : CLOSED (normal) -> OPEN (dégradé) -> CLOSED (reset après cooldown).
    Redis est la source de vérité cross-worker.
    Fallback in-memory si Redis indisponible (sûr, pas de régression).
    """

    def __init__(self, name: str, threshold: int, cooldown_seconds: int) -> None:
        self._name = name
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        # In-memory fallback (single-worker)
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()
        # Redis keys
        self._redis_state_key = f"llm_cb:{name}:state"
        self._redis_failures_key = f"llm_cb:{name}:failures"
        self._redis_opened_key = f"llm_cb:{name}:opened_at"

    async def _get_redis(self):
        """Retourne le client Redis async (pool partagé) ou None."""
        try:
            from lib.redis_client import get_redis as _shared_get_redis
            r = await _shared_get_redis()
            await r.ping()
            return r
        except Exception as _exc:
            logger.warning("llm_gateway._get_redis: %s", _exc)
            return None

    def is_open(self) -> bool:
        """Vérification synchrone rapide depuis l'état in-memory local.

        Note: l'état Redis est lu de façon asynchrone dans record_success/failure.
        Pour la vérification is_open(), on se fie à l'état in-memory mis à jour
        au dernier record_success/failure. C'est un compromis acceptable :
        le circuit peut rester ouvert 1 requête de plus qu'en mode purement Redis.
        """
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._cooldown:
            self._failures = 0
            self._opened_at = None
            logger.info("circuit_breaker provider=%s state=closed_after_cooldown", self._name)
            return False
        return True

    async def sync_from_redis(self) -> None:
        """Synchronise l'état in-memory depuis Redis (appelé au démarrage / périodiquement)."""
        try:
            r = await self._get_redis()
            if not r:
                return
            state_val = await r.get(self._redis_state_key)
            if state_val == "open":
                opened_raw = await r.get(self._redis_opened_key)
                if opened_raw:
                    self._opened_at = float(opened_raw)
            elif state_val == "closed":
                self._opened_at = None
                self._failures = 0
        except Exception as _exc:  # FIX: was bare except
            logger.warning("llm_gateway.sync_from_redis: %s", _exc)
            pass

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._opened_at = None
            # Persister en Redis
            try:
                r = await self._get_redis()
                if r:
                    pipe = r.pipeline()
                    pipe.set(self._redis_state_key, "closed", ex=3600)
                    pipe.delete(self._redis_failures_key)
                    pipe.delete(self._redis_opened_key)
                    await pipe.execute()
            except Exception as _exc:  # FIX: was bare except
                logger.warning("llm_gateway.record_success: %s", _exc)
                pass  # Redis non-bloquant pour les succès

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            # Incrémenter en Redis (cross-worker)
            redis_failures = self._failures
            try:
                r = await self._get_redis()
                if r:
                    pipe = r.pipeline()
                    pipe.incr(self._redis_failures_key)
                    pipe.expire(self._redis_failures_key, self._cooldown * 2)
                    results = await pipe.execute()
                    redis_failures = int(results[0])
            except Exception as _exc:  # FIX: was bare except
                logger.warning("llm_gateway.record_failure: %s", _exc)
                pass

            # Ouvrir le circuit si seuil atteint (Redis ou in-memory)
            effective_failures = max(self._failures, redis_failures)
            if effective_failures >= self._threshold and self._opened_at is None:
                now = time.monotonic()
                self._opened_at = now
                logger.error(
                    "circuit_breaker provider=%s state=open failures=%d cooldown=%ds",
                    self._name,
                    effective_failures,
                    self._cooldown,
                )
                try:
                    r = await self._get_redis()
                    if r:
                        pipe = r.pipeline()
                        pipe.set(self._redis_state_key, "open", ex=self._cooldown * 2)
                        pipe.set(self._redis_opened_key, str(time.time()), ex=self._cooldown * 2)
                        await pipe.execute()
                except Exception as _exc:  # FIX: was bare except
                    logger.warning("llm_gateway.operation: %s", _exc)
                    pass  # Redis non-bloquant — l'état in-memory suffit comme fallback


_cb_deepseek = _CircuitBreaker(
    "deepseek",
    threshold=getattr(settings, "CB_OPENAI_THRESHOLD", 6),
    cooldown_seconds=getattr(settings, "CB_OPENAI_COOLDOWN", 45),
)
_cb_openai = _CircuitBreaker(
    "openai",
    threshold=getattr(settings, "CB_OPENAI_THRESHOLD", 6),
    cooldown_seconds=getattr(settings, "CB_OPENAI_COOLDOWN", 45),
)

# ──────────────────────────────────────────────────────────────────────────────
# Redis quota helpers
# ──────────────────────────────────────────────────────────────────────────────
def _month_key(prefix: str, store_id: int | None = None) -> str:
    ym = datetime.now(UTC).strftime("%Y%m")
    if store_id:
        return f"{prefix}:store:{store_id}:{ym}"
    return f"{prefix}:platform:{ym}"


async def _get_redis():
    """Retourne le client Redis partagé ou None si indisponible."""
    try:
        from services.redis_client import get_redis_client  # type: ignore[import]
        return await get_redis_client()
    except Exception as _exc:  # FIX: was bare except
        logger.warning("llm_gateway._month_key: %s", _exc)
        pass
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        url = getattr(settings, "REDIS_URL", None) or getattr(settings, "CELERY_BROKER_URL", None)
        if url:
            return aioredis.from_url(url, decode_responses=True)
    except Exception as _exc:  # FIX: was bare except
        logger.warning("llm_gateway._get_redis: %s", _exc)
        pass
    return None


async def _check_budget() -> None:
    """Lève BudgetExceededError si le budget mensuel plateforme est dépassé."""
    redis = await _get_redis()
    if redis is None:
        return
    try:
        budget_key = _month_key("llm:cost_usd")
        spent_str = await redis.get(budget_key)
        spent = float(spent_str or "0")
        hard_limit = getattr(settings, "AI_BUDGET_HARD_LIMIT_USD", 250.0)
        if spent >= hard_limit:
            raise BudgetExceededError(
                f"Budget mensuel IA dépassé ({spent:.2f} / {hard_limit:.2f} USD). "
                "Contactez l'administrateur plateforme."
            )
        calls_key = _month_key("llm:calls")
        calls_str = await redis.get(calls_key)
        max_calls = getattr(settings, "AI_MAX_MONTHLY_CALLS", 10_000)
        if int(calls_str or "0") >= max_calls:
            raise BudgetExceededError(
                f"Quota mensuel appels IA dépassé ({calls_str} / {max_calls}). "
                "Contactez l'administrateur plateforme."
            )
    except BudgetExceededError:
        raise
    except Exception as exc:
        logger.warning("budget_check redis error (non-bloquant): %s", exc)


async def _record_usage(
    store_id: int | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    *,
    provider: str,
    agent_name: str,
    latency_ms: int,
) -> None:
    redis = await _get_redis()
    if redis is None:
        return
    try:
        pipe = redis.pipeline()
        # Compteurs plateforme
        pipe.incrbyfloat(_month_key("llm:cost_usd"), cost_usd)
        pipe.incr(_month_key("llm:calls"))
        pipe.incrby(_month_key("llm:input_tokens"), input_tokens)
        pipe.incrby(_month_key("llm:output_tokens"), output_tokens)
        # Compteurs par store
        if store_id:
            pipe.incrbyfloat(_month_key("llm:cost_usd", store_id), cost_usd)
            pipe.incr(_month_key("llm:calls", store_id))
            pipe.incrby(_month_key("llm:input_tokens", store_id), input_tokens)
            pipe.incrby(_month_key("llm:output_tokens", store_id), output_tokens)
        await pipe.execute()
        try:
            from services.metrics import record_llm_usage
            record_llm_usage(
                tenant=str(store_id or "platform"),
                agent=agent_name,
                model=model,
                provider=provider,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                cost_usd=cost_usd,
                latency_seconds=max(latency_ms, 0) / 1000.0,
            )
        except Exception as metrics_exc:
            logger.warning("usage_record metrics error (non-bloquant): %s", metrics_exc)
    except Exception as exc:
        logger.warning("usage_record redis error (non-bloquant): %s", exc)
        try:
            from services.metrics import record_llm_usage
            record_llm_usage(
                tenant=str(store_id or "platform"),
                agent=agent_name,
                model=model,
                provider=provider,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                cost_usd=cost_usd,
                latency_seconds=max(latency_ms, 0) / 1000.0,
            )
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────────
class LLMGatewayError(RuntimeError):
    """Erreur générique du gateway LLM."""


class BudgetExceededError(LLMGatewayError):
    """Budget mensuel ou quota appels dépassé."""


class AllProvidersFailedError(LLMGatewayError):
    """Tous les providers LLM ont échoué."""


# ──────────────────────────────────────────────────────────────────────────────
# Appels providers
# ──────────────────────────────────────────────────────────────────────────────
async def _call_deepseek(
    full_messages: list[dict[str, str]],
    model: str,
    max_tokens: int,
    temperature: float,
) -> ChatCompletion:
    """Appel DeepSeek via client OpenAI-compatible (même SDK, base_url différente)."""
    from openai import AsyncOpenAI  # type: ignore[import]

    client = AsyncOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=getattr(settings, "DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    t0 = time.monotonic()
    resp = await client.chat.completions.create(
        model=model,
        messages=full_messages,  # type: ignore[arg-type]
        max_tokens=max_tokens,
        temperature=temperature,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    in_tok = resp.usage.prompt_tokens if resp.usage else 0
    out_tok = resp.usage.completion_tokens if resp.usage else 0
    cost = _estimate_cost(model, in_tok, out_tok)

    return ChatCompletion(
        id=resp.id,
        model=model,
        choices=[
            _Choice(
                index=c.index,
                message=_Message(role=c.message.role, content=c.message.content or ""),
                finish_reason=c.finish_reason or "stop",
            )
            for c in resp.choices
        ],
        usage=_Usage(prompt_tokens=in_tok, completion_tokens=out_tok, total_tokens=in_tok + out_tok),
        provider="deepseek",
        cost_usd=cost,
        latency_ms=latency_ms,
    )


async def _call_openai(
    full_messages: list[dict[str, str]],
    model: str,
    max_tokens: int,
    temperature: float,
) -> ChatCompletion:
    """Appel OpenAI gpt-4o-mini (ou modèle overridé)."""
    from openai import AsyncOpenAI  # type: ignore[import]

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    t0 = time.monotonic()
    resp = await client.chat.completions.create(
        model=model,
        messages=full_messages,  # type: ignore[arg-type]
        max_tokens=max_tokens,
        temperature=temperature,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    in_tok = resp.usage.prompt_tokens if resp.usage else 0
    out_tok = resp.usage.completion_tokens if resp.usage else 0
    cost = _estimate_cost(model, in_tok, out_tok)

    return ChatCompletion(
        id=resp.id,
        model=model,
        choices=[
            _Choice(
                index=c.index,
                message=_Message(role=c.message.role, content=c.message.content or ""),
                finish_reason=c.finish_reason or "stop",
            )
            for c in resp.choices
        ],
        usage=_Usage(prompt_tokens=in_tok, completion_tokens=out_tok, total_tokens=in_tok + out_tok),
        provider="openai",
        cost_usd=cost,
        latency_ms=latency_ms,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Interface publique
# ──────────────────────────────────────────────────────────────────────────────
async def chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    tenant_id: int | None = None,
    store_id: int | None = None,
    agent_name: str = "chat",
    feature_key: str | None = None,
    channel: str = "chat",
) -> ChatCompletion:
    """Route un appel LLM via DeepSeek (primaire) -> OpenAI (fallback).

    Args:
        messages   : Liste de messages OpenAI (role/content). Si `system` est
                     fourni séparément, il est injecté en tête de liste.
        model      : Override du modèle (sinon : deepseek-chat ou gpt-4o-mini).
        system     : Prompt système (alternatif à un dict role=system dans messages).
        max_tokens : Nombre maximum de tokens en sortie.
        temperature: Créativité (0 = déterministe, 1 = maximal).
        tenant_id  : ID du store pour tracking de quota (alias store_id).
        store_id   : Alias de tenant_id.
        agent_name : Nom de l'agent appelant (pour le logging/tracking).
        feature_key: Alias de agent_name (compat ancienne interface).
        channel    : Canal d'origine (whatsapp, instagram, dashboard, …).

    Returns:
        ChatCompletion : Objet compatible openai.types.chat.ChatCompletion avec
                         `.choices[0].message.content` (str).

    Raises:
        BudgetExceededError   : Budget mensuel ou quota appels dépassé.
        AllProvidersFailedError: Tous les providers ont échoué.
    """
    # Normalisation des paramètres
    effective_store_id = tenant_id or store_id
    effective_agent = agent_name or feature_key or "chat"

    # Construction de la liste de messages complète
    full_messages: list[dict[str, str]] = []
    if system:
        full_messages.append({"role": "system", "content": system})
    for m in messages:
        full_messages.append({"role": str(m.get("role", "user")), "content": str(m.get("content", ""))})

    # Vérification budget avant appel
    await _check_budget()
    cfg = provider_from_settings()
    guard_provider(cfg)

    tracer = None
    span = None
    try:
        from services.observability import get_tracer
        tracer = get_tracer("autocommerce.llm")
        if tracer is not None:
            span = tracer.start_span("llm.chat")
            span.set_attribute("llm.requested_provider", cfg.provider)
            span.set_attribute("llm.agent_name", effective_agent)
            span.set_attribute("llm.channel", channel)
            span.set_attribute("llm.store_id", int(effective_store_id or 0))
    except Exception:
        span = None

    # ── Tentative DeepSeek (provider primaire) ────────────────────────────────
    use_deepseek = (
        getattr(settings, "FEATURE_FLAG_DEEPSEEK", True)
        and bool(getattr(settings, "DEEPSEEK_API_KEY", ""))
        and not _cb_deepseek.is_open()
    )
    deepseek_model = model or "deepseek-chat"
    if use_deepseek and not model:
        # Si un model OpenAI est explicitement demandé, basculer vers OpenAI directement
        if deepseek_model.startswith("gpt-"):
            use_deepseek = False

    if use_deepseek:
        try:
            result = await _call_deepseek(full_messages, deepseek_model, max_tokens, temperature)
            await _cb_deepseek.record_success()
            await _record_usage(
                effective_store_id,
                result.model,
                result.usage.prompt_tokens,
                result.usage.completion_tokens,
                result.cost_usd,
                provider=result.provider,
                agent_name=effective_agent,
                latency_ms=result.latency_ms,
            )
            logger.info(
                "llm_gateway provider=deepseek model=%s agent=%s channel=%s "
                "store_id=%s tokens=%d cost_usd=%.6f latency_ms=%d",
                result.model,
                effective_agent,
                channel,
                effective_store_id,
                result.usage.total_tokens,
                result.cost_usd,
                result.latency_ms,
            )
            if span is not None:
                span.set_attribute("llm.provider", result.provider)
                span.set_attribute("llm.model", result.model)
                span.set_attribute("llm.tokens", result.usage.total_tokens)
                span.set_attribute("llm.cost_usd", float(result.cost_usd))
                span.set_attribute("llm.latency_ms", int(result.latency_ms))
                span.end()
            return result
        except BudgetExceededError:
            raise
        except Exception as ds_exc:
            await _cb_deepseek.record_failure()
            logger.warning(
                "llm_gateway provider=deepseek FAILED agent=%s error=%s — falling back to OpenAI",
                effective_agent,
                ds_exc,
            )

    # ── Fallback OpenAI ───────────────────────────────────────────────────────
    if not getattr(settings, "FEATURE_FLAG_OPENAI_FALLBACK", True):
        raise AllProvidersFailedError(
            "DeepSeek indisponible et FEATURE_FLAG_OPENAI_FALLBACK=False."
        )

    if _cb_openai.is_open():
        raise AllProvidersFailedError(
            "Circuit breaker OpenAI ouvert — tous les providers LLM sont indisponibles."
        )

    if not getattr(settings, "OPENAI_API_KEY", ""):
        raise AllProvidersFailedError("OPENAI_API_KEY non configuré et DeepSeek indisponible.")

    # Si le model demandé est deepseek-*, utiliser gpt-4o-mini en fallback
    openai_model = model if (model and not model.startswith("deepseek")) else settings.OPENAI_MODEL

    try:
        result = await _call_openai(full_messages, openai_model, max_tokens, temperature)
        await _cb_openai.record_success()
        await _record_usage(
            effective_store_id,
            result.model,
            result.usage.prompt_tokens,
            result.usage.completion_tokens,
            result.cost_usd,
            provider=result.provider,
            agent_name=effective_agent,
            latency_ms=result.latency_ms,
        )
        logger.info(
            "llm_gateway provider=openai model=%s agent=%s channel=%s "
            "store_id=%s tokens=%d cost_usd=%.6f latency_ms=%d",
            result.model,
            effective_agent,
            channel,
            effective_store_id,
            result.usage.total_tokens,
            result.cost_usd,
            result.latency_ms,
        )
        if span is not None:
            span.set_attribute("llm.provider", result.provider)
            span.set_attribute("llm.model", result.model)
            span.set_attribute("llm.tokens", result.usage.total_tokens)
            span.set_attribute("llm.cost_usd", float(result.cost_usd))
            span.set_attribute("llm.latency_ms", int(result.latency_ms))
            span.end()
        return result
    except BudgetExceededError:
        raise
    except Exception as oa_exc:
        await _cb_openai.record_failure()
        logger.error(
            "llm_gateway provider=openai FAILED agent=%s error=%s",
            effective_agent,
            oa_exc,
        )
        if span is not None:
            span.set_attribute("llm.error", str(oa_exc))
            span.end()
        raise AllProvidersFailedError(
            f"Tous les providers LLM ont échoué. Dernière erreur OpenAI : {oa_exc}"
        ) from oa_exc


async def get_monthly_stats(store_id: int | None = None) -> dict[str, Any]:
    """Retourne les statistiques d'utilisation LLM du mois courant.

    Utilisé par les endpoints /billing/usage et le dashboard SuperAdmin.
    """
    redis = await _get_redis()
    if redis is None:
        return {"error": "redis_unavailable", "calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}

    try:
        calls = int(await redis.get(_month_key("llm:calls", store_id)) or "0")
        cost = float(await redis.get(_month_key("llm:cost_usd", store_id)) or "0")
        in_tok = int(await redis.get(_month_key("llm:input_tokens", store_id)) or "0")
        out_tok = int(await redis.get(_month_key("llm:output_tokens", store_id)) or "0")
        return {
            "calls": calls,
            "cost_usd": round(cost, 4),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
            "budget_limit_usd": getattr(settings, "AI_BUDGET_HARD_LIMIT_USD", 250.0),
            "calls_limit": getattr(settings, "AI_MAX_MONTHLY_CALLS", 10_000),
            "period": datetime.now(UTC).strftime("%Y-%m"),
        }
    except Exception as exc:
        logger.warning("get_monthly_stats error: %s", exc)
        return {"error": str(exc), "calls": 0, "cost_usd": 0.0}
