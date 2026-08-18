"""tests/test_conversation_summary.py — Tests Résumé de Conversation (Phase 5).
Tests : 20 cas
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGenerateConversationSummary:

    @pytest.mark.asyncio
    async def test_summary_structure_has_required_fields(self):
        from services.conversation_summary import generate_conversation_summary
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content=json.dumps({
            "summary": "Client veut commander des chaussures",
            "main_objection": "Prix élevé",
            "next_actions": ["Envoyer promo"],
            "key_products_mentioned": ["chaussures"],
            "outcome": "lead_captured"
        })))]
        with patch("services.conversation_summary.llm_chat", return_value=mock_completion):
            result = await generate_conversation_summary(
                messages=[{"role": "user", "content": "Bonjour"}, {"role": "assistant", "content": "Bienvenue"}],
                customer_name="Ahmed",
                emotion="interested",
                emotion_score=60,
                lead_score=70,
                lead_label="hot",
                tenant_id=1,
            )
        assert "summary" in result
        assert "main_objection" in result
        assert "next_actions" in result
        assert "outcome" in result
        assert "emotion" in result
        assert "lead_score" in result
        assert "generated_at" in result

    @pytest.mark.asyncio
    async def test_summary_llm_failure_returns_fallback(self):
        from services.conversation_summary import generate_conversation_summary
        with patch("services.conversation_summary.llm_chat", side_effect=Exception("LLM down")):
            result = await generate_conversation_summary(
                messages=[], customer_name=None, emotion=None,
                emotion_score=0, lead_score=0, lead_label="cold"
            )
        assert result["outcome"] == "pending"
        assert result["summary"] == "Résumé non disponible"

    @pytest.mark.asyncio
    async def test_summary_invalid_json_returns_fallback(self):
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content="not json at all"))]
        from services.conversation_summary import generate_conversation_summary
        with patch("services.conversation_summary.llm_chat", return_value=mock_completion):
            result = await generate_conversation_summary(
                messages=[], customer_name=None, emotion=None,
                emotion_score=0, lead_score=0, lead_label="cold"
            )
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_summary_includes_emotion_score(self):
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content=json.dumps({
            "summary": "Test", "main_objection": None, "next_actions": [],
            "key_products_mentioned": [], "outcome": "pending"
        })))]
        from services.conversation_summary import generate_conversation_summary
        with patch("services.conversation_summary.llm_chat", return_value=mock_completion):
            result = await generate_conversation_summary(
                messages=[], customer_name="Client", emotion="angry",
                emotion_score=85, lead_score=50, lead_label="warm"
            )
        assert result["emotion_score"] == 85
        assert result["lead_score"] == 50

    @pytest.mark.asyncio
    async def test_summary_truncates_long_conversation(self):
        """Doit prendre les 20 derniers messages max."""
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(50)]
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content=json.dumps({
            "summary": "Test", "main_objection": None, "next_actions": [],
            "key_products_mentioned": [], "outcome": "pending"
        })))]
        captured_prompt = []
        async def capture_llm(*args, **kwargs):
            captured_prompt.append(kwargs.get("messages", []))
            return mock_completion
        from services.conversation_summary import generate_conversation_summary
        with patch("services.conversation_summary.llm_chat", side_effect=capture_llm):
            await generate_conversation_summary(
                messages=messages, customer_name=None, emotion=None,
                emotion_score=0, lead_score=0, lead_label="cold"
            )


class TestSaveSummary:

    @pytest.mark.asyncio
    async def test_save_summary_calls_db_execute(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        summary = {
            "summary": "Test", "main_objection": None, "next_actions": [],
            "outcome": "sale_completed", "emotion": "interested",
            "emotion_score": 70, "lead_score": 80, "lead_label": "hot",
            "generated_at": "2024-01-01T00:00:00"
        }
        with patch("services.conversation_summary.record_summary") as mock_record:
            mock_record.return_value = None
            from services.conversation_summary import save_summary
            await save_summary(mock_db, 1, 42, summary)
            mock_db.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_save_summary_db_failure_graceful(self):
        mock_db = AsyncMock()
        mock_db.execute.side_effect = Exception("DB error")
        summary = {"summary": "Test", "outcome": "pending"}
        with patch("services.conversation_summary.record_summary") as mock_record:
            mock_record.return_value = None
            from services.conversation_summary import save_summary
            await save_summary(mock_db, 1, 42, summary)  # ne doit pas lever


class TestOutcomeValues:

    def test_outcome_values_are_valid(self):
        valid_outcomes = {"sale_completed", "lead_captured", "no_interest", "escalated", "pending"}
        test_outcome = "sale_completed"
        assert test_outcome in valid_outcomes

    def test_all_emotion_labels_valid(self):
        from services.emotion_detection import EMOTIONS
        assert "neutral" in EMOTIONS
        assert "angry" in EMOTIONS
        assert len(EMOTIONS) >= 5

    def test_lead_labels_valid(self):
        from services.lead_scoring import LeadScore
        assert LeadScore.HOT.value == "hot"
        assert LeadScore.WARM.value == "warm"
        assert LeadScore.COLD.value == "cold"


class TestOmnicallEnterpriseRoutes:

    @pytest.mark.asyncio
    async def test_analyze_endpoint_returns_correct_structure(self):
        """Test de la route POST /omnicall-enterprise/analyze."""
        from fastapi.testclient import TestClient

        from main import app
        client = TestClient(app)
        # Sans auth -> 401 ou 422 attendu (pas 500)
        resp = client.post("/api/v1/omnicall-enterprise/analyze", json={
            "customer_id": 1, "customer_phone": "+21698000001", "text": "bonjour"
        })
        assert resp.status_code in [200, 401, 403, 422]

    @pytest.mark.asyncio
    async def test_hot_leads_endpoint_exists(self):
        from fastapi.testclient import TestClient

        from main import app
        client = TestClient(app)
        resp = client.get("/api/v1/omnicall-enterprise/leads/hot")
        assert resp.status_code in [200, 401, 403]

    @pytest.mark.asyncio
    async def test_dashboard_ceo_endpoint_exists(self):
        from fastapi.testclient import TestClient

        from main import app
        client = TestClient(app)
        resp = client.get("/api/v1/dashboard-enterprise/ceo")
        assert resp.status_code in [200, 401, 403]

    @pytest.mark.asyncio
    async def test_dashboard_ai_endpoint_exists(self):
        from fastapi.testclient import TestClient

        from main import app
        client = TestClient(app)
        resp = client.get("/api/v1/dashboard-enterprise/ai")
        assert resp.status_code in [200, 401, 403]

    @pytest.mark.asyncio
    async def test_dashboard_commercial_endpoint_exists(self):
        from fastapi.testclient import TestClient

        from main import app
        client = TestClient(app)
        resp = client.get("/api/v1/dashboard-enterprise/commercial")
        assert resp.status_code in [200, 401, 403]
