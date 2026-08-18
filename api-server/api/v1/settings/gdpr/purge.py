from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_current_active_user, get_db_session
from models.database import Store, User
from services.audit_log import audit_log
from services.rgpd_purge import purge_store_data

router = APIRouter()

@router.post("/purge", summary="Initiate GDPR data purge for the current store (soft delete + hard delete after delay)")
async def purge_gdpr_data(
    current_user: User = Depends(get_current_active_user),
    db_session: AsyncSession = Depends(get_db_session)
):
    if not current_user.store_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not associated with a store")

    # MFA check would go here in a real application

    store = await db_session.get(Store, current_user.store_id)
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")

    await purge_store_data(store, db_session)
    await audit_log(event_type="GDPR_PURGE_INITIATED", actor_id=current_user.id, store_id=store.id, details={"message": "GDPR purge initiated for store data"})

    return {"message": "GDPR purge initiated. Data will be soft-deleted and hard-deleted after the retention period."}
