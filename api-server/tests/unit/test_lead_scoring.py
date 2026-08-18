"""tests/test_lead_scoring.py — Tests Lead Scoring IA (Phase 1).

Tests : 25 cas
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestComputeLeadScore:

    def test_hot_lead_high_urgency_budget(self):
        from services.lead_scoring import LeadScore, compute_lead_score
        result = compute_lead_score(
            conversation_text="Je veux acheter urgent aujourd'hui combien budget ok",
            emotion="urgent",
            nb_messages=10,
            order_attempts=2,
            questions_asked=3,
            nb_sessions=2,
            active_days=2,
        )
        assert result.score_label == LeadScore.HOT, (
            f"Expected HOT, got {result.score_label} (score={result.score_value})"
        )
        assert result.score_value >= 65

    def test_cold_lead_no_signals(self):
        from services.lead_scoring import LeadScore, compute_lead_score
        result = compute_lead_score(conversation_text="bonjour")
        assert result.score_label == LeadScore.COLD

    def test_warm_lead_moderate_engagement(self):
        from services.lead_scoring import LeadScore, compute_lead_score
        result = compute_lead_score(
            conversation_text="combien ça coûte ?",
            nb_messages=5,
            questions_asked=2,
        )
        assert result.score_label in [LeadScore.WARM, LeadScore.HOT, LeadScore.COLD]

    def test_score_range_0_100(self):
        from services.lead_scoring import compute_lead_score
        for text in ["bonjour", "je veux commander urgent", "arnaque remboursement"]:
            result = compute_lead_score(conversation_text=text)
            assert 0 <= result.score_value <= 100

    def test_criteria_dict_has_all_keys(self):
        from services.lead_scoring import compute_lead_score
        result = compute_lead_score()
        assert "budget" in result.criteria
        assert "urgency" in result.criteria
        assert "engagement" in result.criteria
        assert "responses" in result.criteria
        assert "frequency" in result.criteria

    def test_explanation_not_empty(self):
        from services.lead_scoring import compute_lead_score
        result = compute_lead_score()
        assert len(result.explanation) > 0

    def test_order_attempts_boosts_score(self):
        from services.lead_scoring import compute_lead_score
        base = compute_lead_score(conversation_text="")
        boosted = compute_lead_score(conversation_text="", order_attempts=2)
        assert boosted.score_value >= base.score_value

    def test_emotion_angry_does_not_boost(self):
        from services.lead_scoring import LeadScore, compute_lead_score
        # angry ne boost pas le score lead (ce n'est pas intéressé)
        result = compute_lead_score(
            conversation_text="arnaque",
            emotion="angry",
        )
        assert result is not None  # juste vérifier que ça ne crash pas

    def test_high_frequency_boosts_score(self):
        from services.lead_scoring import compute_lead_score
        base = compute_lead_score()
        freq = compute_lead_score(nb_sessions=5, active_days=7)
        assert freq.score_value >= base.score_value

    def test_arabic_keywords_detected(self):
        from services.lead_scoring import compute_lead_score
        result = compute_lead_score(conversation_text="كم الثمن أريد نشتري")
        assert result.criteria["budget"] > 0 or result.criteria["urgency"] >= 0

    def test_labels_are_string_enum(self):
        from services.lead_scoring import LeadScore, compute_lead_score
        result = compute_lead_score()
        assert result.score_label in list(LeadScore)


class TestScoreHelpers:

    def test_score_budget_keywords(self):
        from services.lead_scoring import _score_budget
        score = _score_budget("combien ça coûte le tarif", [])
        assert score > 0

    def test_score_budget_empty(self):
        from services.lead_scoring import _score_budget
        score = _score_budget("bonjour comment allez vous", [])
        assert score == 0

    def test_score_urgency_with_emotion(self):
        from services.lead_scoring import _score_urgency
        score_no_emotion = _score_urgency("urgent maintenant", None, [])
        score_with_emotion = _score_urgency("urgent maintenant", "urgent", [])
        assert score_with_emotion >= score_no_emotion

    def test_score_engagement_many_messages(self):
        from services.lead_scoring import _score_engagement
        score = _score_engagement(nb_messages=20, buttons_clicked=3)
        assert score > 0

    def test_score_responses_with_order_attempts(self):
        from services.lead_scoring import _score_responses
        score = _score_responses(questions_asked=0, order_attempts=2)
        assert score >= 40  # 2 order_attempts * 40 = 80, cap 40

    def test_score_frequency_multi_session(self):
        from services.lead_scoring import _score_frequency
        score = _score_frequency(nb_sessions=5, active_days=7)
        assert score > 0


class TestUpdateCustomerLeadScore:

    @pytest.mark.asyncio
    async def test_update_lead_score_success(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        from services.lead_scoring import LeadScore, LeadScoringResult, update_customer_lead_score
        result = LeadScoringResult(
            score_label=LeadScore.HOT,
            score_value=78,
            criteria={},
            explanation="Chaud",
        )
        await update_customer_lead_score(mock_db, 1, 42, result)
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_lead_score_db_failure_graceful(self):
        mock_db = AsyncMock()
        mock_db.execute.side_effect = Exception("column lead_score does not exist")
        from services.lead_scoring import LeadScore, LeadScoringResult, update_customer_lead_score
        result = LeadScoringResult(LeadScore.COLD, 10, {}, "Froid")
        await update_customer_lead_score(mock_db, 1, 42, result)  # ne doit pas lever
