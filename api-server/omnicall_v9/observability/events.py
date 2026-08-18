"""Reserved observability event names for OmniCall V9.

VERSION: v24 (événements étendus pour pipeline et Celery)
"""

OBS_EVENT_NAMES: tuple[str, ...] = (
    "omnicall_v9.ingest.received",
    "omnicall_v9.normalize.succeeded",
    "omnicall_v9.normalize.failed",
    "omnicall_v9.route.started",
    "omnicall_v9.route.completed",
    "omnicall_v9.reply.generated",
    "omnicall_v9.pipeline.accepted",
    "omnicall_v9.pipeline.rejected",
    "omnicall_v9.pipeline.token_budget_exceeded",
    "omnicall_v9.shadow.processed",
    "omnicall_v9.shadow.budget_skip",
    "omnicall_v9.active_route.processed",
    "omnicall_v9.active_route.fallback",
    "omnicall_v9.circuit_breaker.opened",
    "omnicall_v9.circuit_breaker.half_open",
    "omnicall_v9.circuit_breaker.closed",
    "omnicall_v9.dedup.skipped",
)
