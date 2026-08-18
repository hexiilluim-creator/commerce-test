"""services/celery_app.py — configuration Celery enterprise."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

try:
    from celery import Celery
    from kombu import Exchange, Queue

    broker_url = os.environ.get('CELERY_BROKER_URL', os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))
    backend_url = os.environ.get('CELERY_RESULT_BACKEND', broker_url)
    orphan_cleanup_interval = int(os.environ.get('ORPHAN_SESSION_CLEANUP_INTERVAL_SECONDS', '1800'))

    celery_app = Celery('autocommerce', broker=broker_url, backend=backend_url)
    _is_test = os.environ.get('ENV', 'production').strip().lower() == 'test'

    def _route_to_dlq(task, exc, task_id, args, kwargs, einfo):
        task_name = getattr(task, 'name', 'unknown')
        try:
            from services.metrics import celery_task_failures, webhook_dlq_pushed_total
            celery_task_failures.labels(task_name=task_name).inc()
            if 'webhook' in task_name or 'whatsapp' in task_name or 'social' in task_name:
                channel = 'social' if 'social' in task_name else 'whatsapp'
                webhook_dlq_pushed_total.labels(channel=channel, reason='task_failure').inc()
        except Exception:
            pass
        logger.error('task routed to DLQ hook task=%s id=%s exc=%s', task_name, task_id, exc)

    _base_config = {
        'task_serializer': 'json',
        'accept_content': ['json'],
        'result_serializer': 'json',
        'timezone': 'UTC',
        'enable_utc': True,
        'task_acks_late': True,
        'worker_prefetch_multiplier': 1,
        'imports': ('services.tasks',),
        'task_default_retry_policy': {
            'max_retries': 5,
            'interval_start': 0,
            'interval_step': 5,
            'interval_max': 120,
        },
        'task_queues': (
            Queue('celery', Exchange('celery'), routing_key='celery'),
            Queue('whatsapp', Exchange('whatsapp'), routing_key='whatsapp'),
            Queue('social', Exchange('social'), routing_key='social'),
            Queue('ai', Exchange('ai'), routing_key='ai'),
            Queue('billing', Exchange('billing'), routing_key='billing'),
            Queue('payments', Exchange('payments'), routing_key='payments'),
            Queue('whatsapp.dlq', Exchange('whatsapp.dlq'), routing_key='whatsapp.dlq'),
            Queue('social.dlq', Exchange('social.dlq'), routing_key='social.dlq'),
            Queue('billing.dlq', Exchange('billing.dlq'), routing_key='billing.dlq'),
            Queue('payments.dlq', Exchange('payments.dlq'), routing_key='payments.dlq'),
            Queue('ai.dlq', Exchange('ai.dlq'), routing_key='ai.dlq'),
        ),
        'task_routes': {
            'services.tasks.process_whatsapp_message': {'queue': 'whatsapp'},
            'services.tasks.send_whatsapp_message': {'queue': 'whatsapp'},
            'services.tasks.process_social_webhook': {'queue': 'social'},
            'services.tasks.reconcile_payment': {'queue': 'payments'},
            'services.tasks.process_ai_response': {'queue': 'ai'},
            'services.tasks.cleanup_orphaned_redis_sessions': {'queue': 'celery'},
        },
        'task_annotations': {
            'services.tasks.process_whatsapp_message': {'on_failure': _route_to_dlq},
            'services.tasks.process_social_webhook': {'on_failure': _route_to_dlq},
            'services.tasks.reconcile_payment': {'on_failure': _route_to_dlq},
            'services.tasks.process_ai_response': {'on_failure': _route_to_dlq},
        },
        'beat_schedule': {
            'cleanup-orphaned-redis-sessions': {
                'task': 'services.tasks.cleanup_orphaned_redis_sessions',
                'schedule': orphan_cleanup_interval,
            },
        },
    }

    if _is_test:
        # V28 P1-fix : garde anti-EAGER. ENV=test force l'exécution synchrone
        # in-process (task_always_eager) ; si un opérateur laisse cette valeur
        # par erreur sur un déploiement de prod, ça sature le worker FastAPI et
        # peut provoquer un dead-lock Redis. On exige une confirmation explicite
        # via ALLOW_CELERY_EAGER_IN_PROD=1 dès qu'un signal de prod est détecté
        # (DEPLOY_ENV/APP_ENV=production, ou un REDIS_URL qui n'est pas localhost).
        _deploy_env = os.environ.get('DEPLOY_ENV', os.environ.get('APP_ENV', '')).strip().lower()
        _looks_like_prod = _deploy_env == 'production' or (
            'localhost' not in broker_url and '127.0.0.1' not in broker_url
        )
        _eager_override = os.environ.get('ALLOW_CELERY_EAGER_IN_PROD', '0').strip().lower() in ('1', 'true', 'yes')

        if _looks_like_prod and not _eager_override:
            raise RuntimeError(
                'celery_app: ENV=test demande task_always_eager mais l\'environnement '
                'ressemble a de la production (DEPLOY_ENV/APP_ENV=production ou broker '
                'non-local). Refus de demarrer pour eviter une saturation FastAPI / '
                'dead-lock Redis. Corrigez ENV, ou definissez explicitement '
                'ALLOW_CELERY_EAGER_IN_PROD=1 si c\'est volontaire.'
            )

        _base_config['task_always_eager'] = True
        _base_config['task_eager_propagates'] = True
        logger.warning('Celery running in EAGER mode (ENV=test) — no broker connection needed')

    celery_app.config_from_object(_base_config)
    celery_app.autodiscover_tasks(['services.tasks'], force=True)

    if not _is_test:
        logger.info('Celery app initialized broker=%s orphan_session_cleanup_interval=%ss', broker_url, orphan_cleanup_interval)
except ImportError:
    celery_app = None
    logger.warning('Celery not installed — async task processing disabled')
