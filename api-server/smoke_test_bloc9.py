from __future__ import annotations

import json
import os

from omnicall_v9.active_router import get_active_route_decision, run_active_v9
from omnicall_v9.observability.shadow_observer import get_shadow_observer

observer = get_shadow_observer()
observer.reset()

results: dict[str, object] = {}

# 1) Flag off
os.environ.pop("OMNICALL_V9_ENABLED", None)
os.environ.pop("OMNICALL_V9_ROLLOUT_PCT", None)
os.environ.pop("OMNICALL_V9_BETA_STORES", None)
decision_off = get_active_route_decision(42)
results["flag_off"] = {
    "active": decision_off.active,
    "reason": decision_off.reason,
}

# 2) Beta stores
os.environ["OMNICALL_V9_ENABLED"] = "1"
os.environ["OMNICALL_V9_BETA_STORES"] = "42,77"
os.environ["OMNICALL_V9_ROLLOUT_PCT"] = "0"
decision_beta = get_active_route_decision(42)
results["beta_store"] = {
    "active": decision_beta.active,
    "reason": decision_beta.reason,
}

# 3) Deterministic rollout bucket
os.environ["OMNICALL_V9_BETA_STORES"] = ""
os.environ["OMNICALL_V9_ROLLOUT_PCT"] = "5"
decision_rollout_a = get_active_route_decision(99)
decision_rollout_b = get_active_route_decision(99)
results["deterministic_rollout"] = {
    "same_result": decision_rollout_a.active == decision_rollout_b.active,
    "same_bucket": decision_rollout_a.bucket == decision_rollout_b.bucket,
    "reason": decision_rollout_a.reason,
    "bucket": decision_rollout_a.bucket,
}

# 4) Active V9 WhatsApp text
wa_result = run_active_v9(
    {
        "from": "+21611111111",
        "id": "wamid.1",
        "type": "text",
        "body": "Bonjour bloc 9",
        "store_id": 42,
        "phone_number_id": "phone_1",
        "trace_id": "trace-wa-1",
    },
    "whatsapp",
    42,
)
results["whatsapp_text"] = {
    "accepted": None if wa_result is None else wa_result.accepted,
    "route": None if wa_result is None else getattr(wa_result.processor_result, "route", None),
}

# 5) Active V9 Instagram image
ig_result = run_active_v9(
    {
        "sender_id": "ig_user_1",
        "recipient_id": "ig_page_1",
        "message_id": "ig-mid-1",
        "type": "image",
        "attachments": [
            {
                "media_id": "att_1",
                "url": "https://example.com/image.jpg",
                "mime_type": "image/jpeg",
            }
        ],
        "raw_event": {"sample": True},
        "raw": {"sample": True},
    },
    "instagram",
    None,
)
results["instagram_image"] = {
    "accepted": None if ig_result is None else ig_result.accepted,
    "route": None if ig_result is None else getattr(ig_result.processor_result, "route", None),
}

# 6) Unsupported route should now be rejected properly
unsupported_result = run_active_v9(
    {
        "from": "+21611111111",
        "id": "wamid.2",
        "type": "location",
        "latitude": 36.8,
        "longitude": 10.1,
        "store_id": 42,
        "phone_number_id": "phone_1",
    },
    "whatsapp",
    42,
)
results["unsupported_location"] = {
    "accepted": None if unsupported_result is None else unsupported_result.accepted,
    "reason": None if unsupported_result is None else unsupported_result.reason,
    "route": None if unsupported_result is None else getattr(unsupported_result.processor_result, "route", None),
}

results["observer_total_events"] = observer.get_report()["total_events"]

print(json.dumps(results, indent=2, default=str))
