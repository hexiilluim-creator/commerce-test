import hashlib
import hmac
import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from services.payment_factory import FlouciProvider, KonnectProvider, PaymeeProvider


@pytest.mark.payments
@given(payload=st.binary(), secret=st.text(min_size=1))
def test_fuzz_flouci_signature(payload, secret):
    provider = FlouciProvider({"webhook_secret": secret})
    # Valid signature
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    headers = {"x-flouci-signature": digest}
    ok, status = provider.verify_webhook_signature(payload, headers)
    assert ok is True
    assert status == "verified"
    
    # Invalid signature
    headers = {"x-flouci-signature": "invalid"}
    ok, status = provider.verify_webhook_signature(payload, headers)
    assert ok is False
    assert status == "invalid"

@pytest.mark.payments
@given(payload=st.binary(), secret=st.text(min_size=1))
def test_fuzz_konnect_signature(payload, secret):
    provider = KonnectProvider({"webhook_secret": secret})
    # Valid signature
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    headers = {"x-signature": digest}
    ok, status = provider.verify_webhook_signature(payload, headers)
    assert ok is True
    assert status == "verified"
    
    # Invalid signature
    headers = {"x-signature": "invalid"}
    ok, status = provider.verify_webhook_signature(payload, headers)
    assert ok is False
    assert status == "invalid"

@pytest.mark.payments
@given(
    api_key=st.text(min_size=1),
    amount=st.floats(min_value=0.001, max_value=1000000.0),
    token=st.text(min_size=1).filter(lambda s: s.strip() != "")
)
def test_fuzz_paymee_checksum(api_key, amount, token):
    provider = PaymeeProvider({"api_key": api_key})
    
    # Normalization logic from PaymeeProvider.verify_webhook_signature
    norm_token = str(token or "").strip()
    amount_f = float(amount)
    checksum = hashlib.sha256(f"{api_key}{amount_f:.3f}{norm_token}".encode()).hexdigest()
    
    payload_dict = {
        "check_sum": checksum,
        "token": token,
        "amount": amount_f
    }
    payload = json.dumps(payload_dict).encode()
    
    ok, status = provider.verify_webhook_signature(payload, {})
    assert ok is True
    assert status == "verified"
    
    # Invalid checksum
    payload_dict["check_sum"] = "invalid"
    payload = json.dumps(payload_dict).encode()
    ok, status = provider.verify_webhook_signature(payload, {})
    assert ok is False
    assert status == "invalid"
