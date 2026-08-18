"""
middleware/current_user.py — Current user_id ContextVar (E12)
==============================================================
Populated by TenantMiddleware from the JWT sub claim.
Used by audit logging to record which user performed each action.
"""

from contextvars import ContextVar

# Set by TenantMiddleware after JWT decode
current_user_id: ContextVar[int | None] = ContextVar("user_id", default=None)
