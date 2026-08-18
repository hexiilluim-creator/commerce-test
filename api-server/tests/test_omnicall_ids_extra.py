import pytest

from omnicall_v9.utils.ids import build_idempotency_key, build_message_fingerprint, build_trace_id


def test_build_message_fingerprint_stability():
    args = {
        "channel": "whatsapp",
        "external_message_id": "msg_123",
        "sender_id": "user_456",
        "extra": "some_body_hash"
    }
    fp1 = build_message_fingerprint(**args)
    fp2 = build_message_fingerprint(**args)
    
    assert fp1 == fp2
    assert fp1.startswith("wha-")
    assert len(fp1) == 4 + 32

def test_build_message_fingerprint_different_inputs():
    fp1 = build_message_fingerprint(channel="whatsapp", external_message_id="1", sender_id="A")
    fp2 = build_message_fingerprint(channel="whatsapp", external_message_id="2", sender_id="A")
    assert fp1 != fp2

def test_build_trace_id():
    tid1 = build_trace_id()
    tid2 = build_trace_id()
    assert tid1.startswith("oc9-")
    assert tid1 != tid2
    assert len(tid1) == 4 + 16

def test_build_idempotency_key():
    key = build_idempotency_key(channel="instagram", store_id=42, message_id="msg_abc")
    assert key == "omnicall:dedup:instagram:42:msg_abc"
    
    key_none = build_idempotency_key(channel="facebook", store_id=None, message_id="msg_xyz")
    assert key_none == "omnicall:dedup:facebook:none:msg_xyz"
