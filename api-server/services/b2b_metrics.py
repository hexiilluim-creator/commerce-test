from __future__ import annotations

from prometheus_client import Counter

b2b_accounts_created_total = Counter(
    "autocommerce_b2b_accounts_created_total",
    "Total B2B company accounts created",
    ["store_id", "account_type"],
)

b2b_quote_requests_total = Counter(
    "autocommerce_b2b_quote_requests_total",
    "Total B2B price quote requests",
    ["store_id"],
)

b2b_orders_created_total = Counter(
    "autocommerce_b2b_orders_created_total",
    "Total B2B orders created",
    ["store_id", "approval_status"],
)

b2b_orders_approved_total = Counter(
    "autocommerce_b2b_orders_approved_total",
    "Total B2B orders approved",
    ["store_id"],
)

b2b_grouped_invoices_created_total = Counter(
    "autocommerce_b2b_grouped_invoices_created_total",
    "Total grouped B2B invoices created",
    ["store_id"],
)
