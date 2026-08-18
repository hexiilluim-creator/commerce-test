"""tests/test_pii_redactor.py — Tests Redacteur PII (Phase 4).
Tests : 20 cas
"""
import logging

import pytest


class TestPIIRedactorString:

    def _redact(self, text: str) -> str:
        from services.pii_redactor import _redact_string
        return _redact_string(text)

    def test_phone_tunisian_redacted(self):
        result = self._redact("Appeler le 98765432")
        assert "98765432" not in result
        assert "[PHONE]" in result

    def test_phone_with_country_code_redacted(self):
        result = self._redact("Mon numéro : +21698000001")
        assert "98000001" not in result

    def test_email_redacted(self):
        result = self._redact("Contact: test@autocommerce.tn")
        assert "test@autocommerce.tn" not in result
        assert "[EMAIL]" in result

    def test_credit_card_redacted(self):
        result = self._redact("Carte : 4111 1111 1111 1111")
        assert "4111" not in result or "[CARD]" in result

    def test_normal_text_unchanged(self):
        text = "Bonjour, voici votre commande"
        result = self._redact(text)
        assert result == text

    def test_arabic_text_preserved(self):
        text = "مرحباً بك في متجرنا"
        result = self._redact(text)
        assert "مرحباً" in result

    def test_multiple_phones_all_redacted(self):
        result = self._redact("98765432 et 55000001 sont nos numéros")
        assert "98765432" not in result
        assert "55000001" not in result

    def test_multiple_emails_redacted(self):
        result = self._redact("Envoyez à a@b.com et c@d.tn")
        assert "a@b.com" not in result
        assert "c@d.tn" not in result

    def test_mixed_pii_all_redacted(self):
        text = "Client: 98765432, email: client@test.tn, carte: 4111 1111 1111 1111"
        result = self._redact(text)
        assert "98765432" not in result
        assert "client@test.tn" not in result

    def test_empty_string(self):
        assert self._redact("") == ""


class TestPIIRedactorRecursive:

    def _redact(self, obj):
        from services.pii_redactor import _redact_recursive
        return _redact_recursive(obj)

    def test_dict_values_redacted(self):
        result = self._redact({"phone": "98765432", "text": "hello"})
        assert "98765432" not in result["phone"]
        assert result["text"] == "hello"

    def test_nested_dict_redacted(self):
        result = self._redact({"user": {"phone": "98765432"}})
        assert "98765432" not in result["user"]["phone"]

    def test_list_items_redacted(self):
        result = self._redact(["98765432", "hello", "test@x.com"])
        assert "98765432" not in result[0]
        assert result[1] == "hello"
        assert "test@x.com" not in result[2]

    def test_int_passed_through(self):
        assert self._redact(42) == 42

    def test_none_passed_through(self):
        assert self._redact(None) is None


class TestPIIRedactorFilter:

    def test_filter_installed_on_root_logger(self):
        from services.pii_redactor import PIIRedactorFilter, install_pii_redactor
        root = logging.getLogger()
        # Retirer les filtres existants de type PIIRedactorFilter pour tester proprement
        root.filters = [f for f in root.filters if not isinstance(f, PIIRedactorFilter)]
        install_pii_redactor()
        has_filter = any(isinstance(f, PIIRedactorFilter) for f in root.filters)
        assert has_filter

    def test_install_twice_no_duplicate(self):
        from services.pii_redactor import PIIRedactorFilter, install_pii_redactor
        install_pii_redactor()
        install_pii_redactor()
        root = logging.getLogger()
        count = sum(1 for f in root.filters if isinstance(f, PIIRedactorFilter))
        assert count == 1

    def test_filter_redacts_log_message(self):
        from services.pii_redactor import PIIRedactorFilter
        f = PIIRedactorFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Client 98765432 a commandé", args=(), exc_info=None
        )
        f.filter(record)
        assert "98765432" not in record.msg
        assert "[PHONE]" in record.msg

    def test_filter_redacts_log_args(self):
        from services.pii_redactor import PIIRedactorFilter
        f = PIIRedactorFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Phone: %s", args=("98765432",), exc_info=None
        )
        f.filter(record)
        assert "98765432" not in str(record.args)
