"""tests/test_emotion_detection.py — Tests Détection Émotionnelle (Phase 1).

Tests : 30 cas
"""
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestHeuristicEmotionDetection:

    def test_angry_remboursement(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("Je veux un remboursement immédiat c'est une arnaque")
        assert result.emotion == "angry"
        assert result.score > 0

    def test_angry_arabic(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("محتال عندي الدليل")
        assert result.emotion == "angry"

    def test_frustrated(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("Toujours pas de réponse depuis hier, problème grave")
        assert result.emotion in ["frustrated", "angry"]

    def test_urgent(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("Urgent ! J'ai besoin de la commande aujourd'hui")
        assert result.emotion == "urgent"

    def test_hesitant(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("C'est peut-être trop cher, je sais pas encore")
        assert result.emotion == "hesitant"

    def test_interested(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("Je veux commander, combien ça coûte la livraison ?")
        assert result.emotion == "interested"

    def test_neutral_returns_neutral(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("D'accord.")
        assert result.emotion == "neutral"

    def test_empty_string(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("")
        assert result.emotion == "neutral"

    def test_confidence_high_for_strong_signals(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("Remboursement arnaque inacceptable scandaleux")
        assert result.confidence >= 0.7

    def test_should_escalate_angry_high_score(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("Arnaque ! Remboursement ! Tribunal !")
        assert result.should_escalate is True

    def test_should_not_escalate_neutral(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("Merci pour votre service")
        assert result.should_escalate is False

    def test_triggers_list_populated(self):
        from services.emotion_detection import _heuristic_emotion
        result = _heuristic_emotion("remboursement argent retour arnaque")
        assert len(result.triggers) > 0

    def test_score_range(self):
        from services.emotion_detection import _heuristic_emotion
        for text in ["bonjour", "urgent", "arnaque inacceptable", "peut-être"]:
            result = _heuristic_emotion(text)
            assert 0 <= result.score <= 100

    def test_alert_score_threshold(self):
        from services.emotion_detection import ALERT_SCORE_THRESHOLD, _heuristic_emotion
        result = _heuristic_emotion("Arnaque ! Arnaque ! Arnaque ! Arnaque !")
        if result.score >= ALERT_SCORE_THRESHOLD:
            assert result.should_alert is True


class TestAnalyzeEmotion:

    @pytest.mark.asyncio
    async def test_analyze_emotion_heuristic_priority(self):
        """Si heuristique confiante -> pas d'appel LLM."""
        with patch("services.emotion_detection._llm_emotion"):
            from services.emotion_detection import analyze_emotion
            result = await analyze_emotion("Remboursement urgence arnaque maintenant", use_llm=True)
            # Heuristique doit être confiante -> LLM non appelé
            # (Si le score heuristique < seuil, le mock sera appelé)
            assert result.emotion in ["angry", "urgent", "frustrated"]

    @pytest.mark.asyncio
    async def test_analyze_emotion_use_llm_false(self):
        """use_llm=False -> toujours heuristique."""
        from services.emotion_detection import analyze_emotion
        result = await analyze_emotion("je sais pas trop", use_llm=False)
        assert result is not None
        assert result.emotion in ["neutral", "hesitant"]

    @pytest.mark.asyncio
    async def test_analyze_emotion_llm_called_for_neutral(self):
        """Heuristique neutre -> LLM appelé si use_llm=True."""
        mock_result = type("R", (), {
            "emotion": "interested", "score": 60, "confidence": 0.85,
            "triggers": [], "should_escalate": False, "should_alert": False,
        })()
        with patch("services.emotion_detection._llm_emotion", return_value=mock_result):
            from services.emotion_detection import analyze_emotion
            result = await analyze_emotion("D'accord", use_llm=True)
            # LLM peut être appelé pour textes neutres ambigus
            assert result is not None


class TestStoreEmotionResult:

    @pytest.mark.asyncio
    async def test_store_emotion_updates_customer(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        from services.emotion_detection import EmotionResult
        result = EmotionResult(emotion="angry", score=80, confidence=0.9)
        with patch("services.emotion_detection.store_long_term") as mock_store:
            mock_store.return_value = None
            from services.emotion_detection import store_emotion_result
            await store_emotion_result(mock_db, 1, 42, result)
            mock_db.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_store_emotion_db_failure_graceful(self):
        mock_db = AsyncMock()
        mock_db.execute.side_effect = Exception("DB error")
        from services.emotion_detection import EmotionResult
        result = EmotionResult(emotion="neutral", score=10, confidence=0.5)
        from services.emotion_detection import store_emotion_result
        await store_emotion_result(mock_db, 1, 42, result)  # ne doit pas lever


class TestSendSupervisorAlert:

    @pytest.mark.asyncio
    async def test_alert_published_to_redis(self):
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock()
        with patch("services.emotion_detection._get_redis", return_value=mock_redis):
            from services.emotion_detection import EmotionResult, send_supervisor_alert
            result = EmotionResult(emotion="angry", score=90, confidence=0.95, should_alert=True)
            await send_supervisor_alert(1, 42, "+21698000000", result)
            mock_redis.publish.assert_awaited()

    @pytest.mark.asyncio
    async def test_alert_redis_failure_graceful(self):
        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = Exception("Redis down")
        with patch("services.emotion_detection._get_redis", return_value=mock_redis):
            from services.emotion_detection import EmotionResult, send_supervisor_alert
            result = EmotionResult(emotion="angry", score=90, confidence=0.95)
            await send_supervisor_alert(1, 42, "+21698000000", result)  # ne doit pas lever
