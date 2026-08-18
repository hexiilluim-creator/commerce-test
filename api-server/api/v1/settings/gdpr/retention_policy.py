from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

router = APIRouter()

class RetentionPolicy(BaseModel):
    customer_data_retention_days: int = 365 * 5  # 5 years
    order_data_retention_days: int = 365 * 10 # 10 years
    message_log_retention_days: int = 365 * 1 # 1 year
    audit_log_retention_days: int = 365 * 10 # 10 years

@router.get("/retention-policy", response_model=RetentionPolicy)
async def get_retention_policy():
    """Retourne la politique de rétention des données RGPD."""
    return RetentionPolicy()
