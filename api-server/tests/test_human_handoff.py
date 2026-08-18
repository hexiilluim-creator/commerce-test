"""tests/test_human_handoff.py — Tests Escalade Humaine (Phase 1).

Tests : 25 cas
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDetectHandoffTriggers:

    def test_refund_trigger(self):
        from services.human_handoff_service import HandoffReason, detect_handoff_triggers
        reasons = detect_handoff_triggers("Je veux un remboursement immédiat")
        assert HandoffReason.REFUND_REQUEST in reasons

    def test_dispute_trigger_arabic(self):
        from services.human_handoff_service import HandoffReason, detect_handoff_triggers
        reasons = detect_handoff_triggers("سأرفع دعوى قضائية")
        assert HandoffReason.DISPUTE in reasons

    def test_churn_threat(self):
        from services.human_handoff_service import HandoffReason, detect_handoff_triggers
        reasons = detect_handoff_triggers("Je vais partir chez vos concurrents jamais plus")
        assert HandoffReason.CHURN_THREAT in reasons

    def test_high_dissatisfaction(self):
        from services.human_handoff_service import HandoffReason, detect_handoff_triggers
        reasons = detect_handoff_triggers("Je suis très déçu c'est inacceptable")
        assert HandoffReason.HIGH_DISSATISFACTION in reasons

    def test_no_trigger_normal_message(self):
        from services.human_handoff_service import detect_handoff_triggers
        reasons = detect_handoff_triggers("Bonjour, je voudrais commander")
        assert len(reasons) == 0

    def test_multiple_triggers(self):
        from services.human_handoff_service import detect_handoff_triggers
        reasons = detect_handoff_triggers("Remboursement ! Arnaque ! Partir !")
        assert len(reasons) >= 2


class TestShouldEscalate:

    @pytest.mark.asyncio
    async def test_escalate_for_angry_emotion(self):
        from services.human_handoff_service import HandoffReason, should_escalate
        escalate, reasons = await should_escalate("ok", emotion="angry", emotion_score=80)
        assert escalate is True
        assert HandoffReason.ANGER_DETECTED in reasons

    @pytest.mark.asyncio
    async def test_escalate_for_urgent_high_score(self):
        from services.human_handoff_service import HandoffReason, should_escalate
        escalate, reasons = await should_escalate("besoin urgent", emotion="urgent", emotion_score=75)
        assert escalate is True

    @pytest.mark.asyncio
    async def test_no_escalate_neutral(self):
        from services.human_handoff_service import should_escalate
        escalate, reasons = await should_escalate("Bonjour merci", emotion="neutral", emotion_score=10)
        assert escalate is False
        assert len(reasons) == 0

    @pytest.mark.asyncio
    async def test_urgent_low_score_no_escalate(self):
        from services.human_handoff_service import HandoffReason, should_escalate
        escalate, reasons = await should_escalate("un peu urgent", emotion="urgent", emotion_score=30)
        # emotion_score < 70 -> URGENCY_DETECTED non ajouté
        assert HandoffReason.URGENCY_DETECTED not in reasons

    @pytest.mark.asyncio
    async def test_text_trigger_overrides_emotion(self):
        from services.human_handoff_service import HandoffReason, should_escalate
        escalate, reasons = await should_escalate(
            "Je veux un remboursement maintenant", emotion="neutral", emotion_score=0
        )
        assert escalate is True
        assert HandoffReason.REFUND_REQUEST in reasons


class TestCreateHandoff:

    @pytest.mark.asyncio
    async def test_create_handoff_success(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        from services.human_handoff_service import HandoffReason
        with patch("services.human_handoff_service._publish_handoff_alert"):
            from services.human_handoff_service import create_handoff
            result = await create_handoff(
                mock_db, 1, 42, "+21698000000",
                [HandoffReason.REFUND_REQUEST], "Je veux un remboursement"
            )
            assert result["status"] == "open"
            assert "handoff_id" in result

    @pytest.mark.asyncio
    async def test_create_handoff_db_failure_returns_error(self):
        mock_db = AsyncMock()
        mock_db.execute.side_effect = Exception("DB error")
        from services.human_handoff_service import HandoffReason, create_handoff
        result = await create_handoff(mock_db, 1, 42, "+21698", [HandoffReason.MANUAL], "")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_create_handoff_publishes_alert(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_db.execute.return_value = mock_result
        from services.human_handoff_service import HandoffReason
        with patch("services.human_handoff_service._publish_handoff_alert") as mock_pub:
            mock_pub.return_value = None
            from services.human_handoff_service import create_handoff
            await create_handoff(mock_db, 1, 42, "+21698", [HandoffReason.ANGER_DETECTED], "test")
            mock_pub.assert_called_once()


class TestResolveHandoff:

    @pytest.mark.asyncio
    async def test_resolve_handoff_success(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        from services.human_handoff_service import resolve_handoff
        result = await resolve_handoff(mock_db, 1, 1, "Agent Ahmed", "Remboursé")
        assert result is True

    @pytest.mark.asyncio
    async def test_resolve_handoff_db_failure_returns_false(self):
        mock_db = AsyncMock()
        mock_db.execute.side_effect = Exception("DB error")
        from services.human_handoff_service import resolve_handoff
        result = await resolve_handoff(mock_db, 999, 1, "Agent", "")
        assert result is False


class TestGetOpenHandoffs:

    @pytest.mark.asyncio
    async def test_get_open_handoffs_returns_list(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {"id": 1, "customer_phone": "+21698", "reasons": ["angry"], "created_at": None}
        ]
        mock_db.execute.return_value = mock_result
        from services.human_handoff_service import get_open_handoffs
        result = await get_open_handoffs(mock_db, 1, limit=10)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_open_handoffs_db_failure_returns_empty(self):
        mock_db = AsyncMock()
        mock_db.execute.side_effect = Exception("DB error")
        from services.human_handoff_service import get_open_handoffs
        result = await get_open_handoffs(mock_db, 1)
        assert result == []
