"""services/metrics.py — métriques Prometheus enterprise avec fallback no-op."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class _NoOpMetric:
    def labels(self, *args, **kwargs):
        return self
    def inc(self, amount: float = 1):
        return None
    def dec(self, amount: float = 1):
        return None
    def observe(self, amount: float):
        return None
    def set(self, value: float):
        return None


try:
    from prometheus_client import Counter, Gauge, Histogram

    webhook_events_total = Counter(
        'autocommerce_webhook_events_total',
        'Total webhook events received',
        ['channel', 'event_type'],
    )
    webhook_inflight = Gauge(
        'autocommerce_webhook_inflight',
        'Webhook events currently being processed',
        ['channel'],
    )
    webhook_processing_duration_seconds = Histogram(
        'autocommerce_webhook_processing_duration_seconds',
        'Webhook processing duration in seconds',
        ['channel', 'outcome'],
    )
    webhook_latency_seconds = Histogram(
        'autocommerce_webhook_latency_seconds',
        'End-to-end webhook processing latency (reception -> 200 OK)',
        ['channel'],
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
    )
    webhook_dedup_hits_total = Counter(
        'autocommerce_webhook_dedup_hits_total',
        'Duplicate webhooks dropped by idempotency layer',
        ['channel', 'outcome'],
    )
    webhook_dlq_pushed_total = Counter(
        'autocommerce_webhook_dlq_pushed_total',
        'Webhooks routed to DLQ after retries',
        ['channel', 'reason'],
    )

    fsm_transitions_total = Counter(
        'autocommerce_fsm_transitions_total',
        'FSM state transitions',
        ['store_id', 'from_state', 'to_state'],
    )
    emotion_detections_total = Counter(
        'autocommerce_emotion_detections_total',
        'Emotion detection results',
        ['emotion', 'method'],
    )
    human_handoffs_total = Counter(
        'autocommerce_human_handoffs_total',
        'Human handoff escalations created',
        ['store_id', 'reason'],
    )

    lead_score_distribution = Histogram(
        'autocommerce_lead_score_distribution',
        'Distribution of computed lead scores',
        buckets=[0, 10, 20, 35, 50, 65, 80, 90, 100],
    )
    ai_credits_consumed_total = Counter(
        'autocommerce_ai_credits_consumed_total',
        'AI credits consumed',
        ['store_id', 'agent_name'],
    )
    billing_events_total = Counter(
        'autocommerce_billing_events_total',
        'Billing events processed',
        ['event_type', 'provider'],
    )
    api_request_duration_seconds = Histogram(
        'autocommerce_api_request_duration_seconds',
        'API request duration',
        ['method', 'endpoint', 'status_code'],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    )
    tenant_active_total = Gauge(
        'autocommerce_tenant_active_total',
        'Number of currently active tenants',
    )
    redis_operations_total = Counter(
        'autocommerce_redis_operations_total',
        'Redis operations',
        ['operation', 'outcome'],
    )
    llm_calls_total = Counter(
        'autocommerce_llm_calls_total',
        'LLM API calls',
        ['provider', 'model', 'agent_name', 'outcome'],
    )
    llm_provider_used_total = Counter(
        'autocommerce_llm_provider_used_total',
        'Nombre d\'utilisations d\'un provider LLM',
        ['provider'],
    )
    llm_tokens_total = Counter(
        'autocommerce_llm_tokens_total',
        'LLM tokens consumed',
        ['provider', 'model', 'token_type'],
    )
    autocommerce_prompt_tokens_total = Counter(
        'autocommerce_prompt_tokens_total',
        'Prompt tokens per tenant/agent/model',
        ['tenant', 'agent', 'model'],
    )
    autocommerce_completion_tokens_total = Counter(
        'autocommerce_completion_tokens_total',
        'Completion tokens per tenant/agent/model',
        ['tenant', 'agent', 'model'],
    )
    autocommerce_llm_cost_usd_total = Counter(
        'autocommerce_llm_cost_usd_total',
        'Estimated LLM cost aggregated by tenant/agent/model',
        ['tenant', 'agent', 'model'],
    )
    autocomplete_llm_latency_seconds = Histogram(
        'autocommerce_llm_latency_seconds',
        'LLM latency by tenant/agent/model/provider',
        ['tenant', 'agent', 'model', 'provider'],
        buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20],
    )

    message_queue_length = Gauge(
        'autocommerce_message_queue_length',
        'Number of messages in the WhatsApp processing queue',
        ['queue'],
    )
    message_queue_dlq_length = Gauge(
        'autocommerce_message_queue_dlq_length',
        'Number of messages in the DLQ',
    )
    message_queue_pending = Gauge(
        'autocommerce_message_queue_pending',
        'Number of pending messages in consumer groups',
        ['consumer_group'],
    )
    active_conversations_total = Gauge(
        'autocommerce_active_conversations_total',
        'Number of active conversations',
    )
    openai_errors_total = Counter(
        'autocommerce_openai_errors_total',
        'OpenAI/LLM API errors by type',
        ['error_type', 'agent_name'],
    )
    message_processing_duration_seconds = Histogram(
        'autocommerce_message_processing_duration_seconds',
        'Time to process a WhatsApp message through the AI pipeline',
        ['store_id', 'intent'],
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
    )
    store_resolver_lookups_total = Counter(
        'autocommerce_store_resolver_lookups_total',
        'Store resolver lookups by channel/source/outcome',
        ['channel', 'source', 'outcome'],
    )
    celery_task_retries = Counter(
        'autocommerce_celery_task_retries_total',
        'Celery retries triggered',
        ['task_name'],
    )
    celery_task_failures = Counter(
        'autocommerce_celery_task_failures_total',
        'Celery task failures / DLQ routing',
        ['task_name'],
    )
    upload_validation_total = Counter(
        'autocommerce_upload_validation_total',
        'Uploads accepted/rejected by validation layer',
        ['allow_kind', 'outcome'],
    )
    orders_created_total = Counter(
        'autocommerce_orders_created_total',
        'Orders created by tenant and channel',
        ['store_id', 'channel'],
    )
    celery_stub_invocations_total = Counter(
        'autocommerce_celery_stub_invocations_total',
        'P1.6-FIX : tâches Celery appelées alors que le broker/package Celery est '
        'absent (mode stub silencieux) — devrait TOUJOURS être à 0 en production. '
        "Toute valeur > 0 signifie qu'un message WhatsApp, une notification de "
        "commande, ou une réconciliation de paiement a été perdue silencieusement.",
        ['task_name'],
    )

except ImportError:
    logger.warning('prometheus_client not installed — using no-op metrics stubs')
    webhook_events_total = webhook_inflight = webhook_processing_duration_seconds = webhook_latency_seconds = _NoOpMetric()
    webhook_dedup_hits_total = webhook_dlq_pushed_total = _NoOpMetric()
    fsm_transitions_total = emotion_detections_total = human_handoffs_total = lead_score_distribution = _NoOpMetric()
    ai_credits_consumed_total = billing_events_total = api_request_duration_seconds = tenant_active_total = _NoOpMetric()
    redis_operations_total = llm_calls_total = llm_tokens_total = llm_provider_used_total = _NoOpMetric()
    autocommerce_prompt_tokens_total = autocommerce_completion_tokens_total = autocommerce_llm_cost_usd_total = _NoOpMetric()
    autocomplete_llm_latency_seconds = _NoOpMetric()
    message_queue_length = message_queue_dlq_length = message_queue_pending = active_conversations_total = _NoOpMetric()
    openai_errors_total = message_processing_duration_seconds = _NoOpMetric()
    store_resolver_lookups_total = celery_task_retries = celery_task_failures = _NoOpMetric()
    upload_validation_total = orders_created_total = _NoOpMetric()
    celery_stub_invocations_total = _NoOpMetric()


def record_llm_usage(*, tenant: str, agent: str, model: str, provider: str, prompt_tokens: int, completion_tokens: int, cost_usd: float, latency_seconds: float, outcome: str = 'success') -> None:
    llm_calls_total.labels(provider=provider, model=model, agent_name=agent, outcome=outcome).inc()
    llm_provider_used_total.labels(provider=provider).inc()
    llm_tokens_total.labels(provider=provider, model=model, token_type='prompt').inc(prompt_tokens)
    llm_tokens_total.labels(provider=provider, model=model, token_type='completion').inc(completion_tokens)
    autocommerce_prompt_tokens_total.labels(tenant=tenant, agent=agent, model=model).inc(prompt_tokens)
    autocommerce_completion_tokens_total.labels(tenant=tenant, agent=agent, model=model).inc(completion_tokens)
    autocommerce_llm_cost_usd_total.labels(tenant=tenant, agent=agent, model=model).inc(cost_usd)
    autocomplete_llm_latency_seconds.labels(tenant=tenant, agent=agent, model=model, provider=provider).observe(latency_seconds)
