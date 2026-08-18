"""omnicall_v9/circuit_breaker.py — Circuit Breaker V9 avec état Redis-backed.

Implémentation du pattern Circuit Breaker à 3 états :
- CLOSED (normal) : V9 actif, erreurs comptées
- OPEN (dégradé) : V9 désactivé après pic d'erreurs
- HALF_OPEN (test) : V9 partiellement réactivé pour sonder la récupération

Améliorations v24 :
- État Redis-backed (cohérent entre workers Celery)
- État HALF_OPEN pour une récupération graduelle
- TTL automatique des erreurs dans Redis
- Fallback in-memory si Redis indisponible
- Thread-safe

VERSION: v24
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from enum import Enum, StrEnum

logger = logging.getLogger("omnicall_v9.circuit_breaker")

_REDIS_CB_KEY = "omnicall_v9:circuit_breaker:state"
_REDIS_ERROR_KEY = "omnicall_v9:circuit_breaker:errors"
_REDIS_LAST_OPEN_KEY = "omnicall_v9:circuit_breaker:last_open"


class CBState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit Breaker Redis-backed avec état HALF_OPEN.

    Stratégie de reset :
    - Après `reset_timeout_seconds` en état OPEN, passage en HALF_OPEN.
    - En HALF_OPEN, si une erreur survient : retour en OPEN.
    - En HALF_OPEN, si `half_open_success_threshold` succès consécutifs :
      passage en CLOSED.
    """

    def __init__(
        self,
        error_threshold: int = 5,
        window_seconds: int = 60,
        reset_timeout_seconds: int = 300,
        half_open_success_threshold: int = 3,
    ) -> None:
        self.error_threshold = error_threshold
        self.window_seconds = window_seconds
        self.reset_timeout_seconds = reset_timeout_seconds
        self.half_open_success_threshold = half_open_success_threshold

        # État in-memory (fallback si Redis indisponible)
        self._lock = threading.Lock()
        self._errors: list[float] = []
        self._state: CBState = CBState.CLOSED
        self._last_open_at: float | None = None
        self._half_open_successes: int = 0

    def _get_redis(self):
        """Retourne le client Redis synchrone ou None si indisponible."""
        try:
            import os

            import redis as redis_lib
            url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            client = redis_lib.Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
            client.ping()
            return client
        except Exception:
            return None

    def _redis_get_state(self) -> CBState | None:
        try:
            r = self._get_redis()
            if not r:
                return None
            val = r.get(_REDIS_CB_KEY)
            if val:
                return CBState(val.decode())
            return None
        except Exception:
            return None

    def _redis_set_state(self, state: CBState, ttl_seconds: int = 3600) -> None:
        try:
            r = self._get_redis()
            if r:
                r.setex(_REDIS_CB_KEY, ttl_seconds, state.value)
        except Exception:
            pass

    def _redis_incr_errors(self) -> int:
        """Incrémente le compteur d'erreurs dans Redis avec TTL glissant."""
        try:
            r = self._get_redis()
            if not r:
                return 0
            count = r.incr(_REDIS_ERROR_KEY)
            r.expire(_REDIS_ERROR_KEY, self.window_seconds)
            return int(count)
        except Exception:
            return 0

    def _redis_get_errors(self) -> int:
        try:
            r = self._get_redis()
            if not r:
                return 0
            val = r.get(_REDIS_ERROR_KEY)
            return int(val) if val else 0
        except Exception:
            return 0

    def _redis_reset_errors(self) -> None:
        try:
            r = self._get_redis()
            if r:
                r.delete(_REDIS_ERROR_KEY)
        except Exception:
            pass

    def _redis_set_last_open(self, ts: float) -> None:
        try:
            r = self._get_redis()
            if r:
                r.setex(_REDIS_LAST_OPEN_KEY, self.reset_timeout_seconds * 2, str(ts))
        except Exception:
            pass

    def _redis_get_last_open(self) -> float | None:
        try:
            r = self._get_redis()
            if not r:
                return None
            val = r.get(_REDIS_LAST_OPEN_KEY)
            return float(val) if val else None
        except Exception:
            return None

    def record_failure(self) -> None:
        """Alias for record_error to match tests."""
        self.record_error()

    def record_error(self) -> None:
        """Enregistre une erreur et vérifie si le circuit doit s'ouvrir."""
        with self._lock:
            now = time.time()

            # Tentative Redis-first
            redis_errors = self._redis_incr_errors()
            if redis_errors > 0:
                error_count = redis_errors
            else:
                # Fallback in-memory
                cutoff = now - self.window_seconds
                self._errors = [t for t in self._errors if t > cutoff]
                self._errors.append(now)
                error_count = len(self._errors)

            # Vérification du seuil
            if error_count >= self.error_threshold:
                current_state = self._redis_get_state() or self._state
                if current_state != CBState.OPEN:
                    logger.critical(
                        "OMNICALL_V9_CIRCUIT_BREAKER_OPENED",
                        extra={
                            "error_count": error_count,
                            "threshold": self.error_threshold,
                            "window_seconds": self.window_seconds,
                        },
                    )
                    self._state = CBState.OPEN
                    self._last_open_at = now
                    self._redis_set_state(CBState.OPEN)
                    self._redis_set_last_open(now)
                elif current_state == CBState.HALF_OPEN:
                    # Erreur en HALF_OPEN -> retour en OPEN
                    logger.warning("OMNICALL_V9_CIRCUIT_BREAKER_HALF_OPEN_FAILED")
                    self._state = CBState.OPEN
                    self._last_open_at = now
                    self._redis_set_state(CBState.OPEN)
                    self._redis_set_last_open(now)
                    self._half_open_successes = 0

    def record_success(self) -> None:
        """Enregistre un succès (utile en état HALF_OPEN pour la récupération)."""
        with self._lock:
            state = self._redis_get_state() or self._state
            if state == CBState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.half_open_success_threshold:
                    logger.info(
                        "OMNICALL_V9_CIRCUIT_BREAKER_CLOSED",
                        extra={"successes": self._half_open_successes},
                    )
                    self._state = CBState.CLOSED
                    self._redis_set_state(CBState.CLOSED)
                    self._redis_reset_errors()
                    self._half_open_successes = 0

    def should_allow_request(self) -> bool:
        """Alias for is_v9_safe to match tests."""
        return self.is_v9_safe()

    def is_v9_safe(self) -> bool:
        """Retourne True si V9 peut traiter des messages (état CLOSED ou HALF_OPEN)."""
        with self._lock:
            # Lire l'état depuis Redis (source de vérité cross-worker)
            state = self._redis_get_state()
            if state is None:
                state = self._state
            else:
                self._state = state

            if state == CBState.CLOSED:
                return True

            if state == CBState.HALF_OPEN:
                return True  # On laisse passer pour tester la récupération

            # state == OPEN : vérifier si le timeout de reset est écoulé
            last_open = self._redis_get_last_open() or self._last_open_at
            if last_open is None:
                return True

            elapsed = time.time() - last_open
            if elapsed >= self.reset_timeout_seconds:
                logger.info(
                    "OMNICALL_V9_CIRCUIT_BREAKER_HALF_OPEN",
                    extra={"elapsed_seconds": round(elapsed, 1)},
                )
                self._state = CBState.HALF_OPEN
                self._half_open_successes = 0
                self._redis_set_state(CBState.HALF_OPEN)
                self._redis_reset_errors()
                return True

            return False

    def get_state(self) -> CBState:
        """Retourne l'état actuel du circuit breaker avec logique de cooldown."""
        # 1. Lire l'état (Redis ou local)
        state = self._redis_get_state() or self._state
        
        # 2. Si OPEN, vérifier si on doit passer en HALF_OPEN (cooldown)
        if state == CBState.OPEN:
            last_open = self._redis_get_last_open() or self._last_open_at
            if last_open is not None:
                elapsed = time.time() - last_open
                if elapsed >= self.reset_timeout_seconds:
                    # On ne met pas à jour self._state ici pour rester thread-safe/idempotent,
                    # mais on retourne l'état logique attendu.
                    return CBState.HALF_OPEN
        
        return state

    def reset(self) -> None:
        """Remet le circuit breaker à CLOSED (usage tests/admin)."""
        with self._lock:
            self._state = CBState.CLOSED
            self._errors = []
            self._last_open_at = None
            self._half_open_successes = 0
            self._redis_set_state(CBState.CLOSED)
            self._redis_reset_errors()


# Instance globale
v9_circuit = CircuitBreaker()
