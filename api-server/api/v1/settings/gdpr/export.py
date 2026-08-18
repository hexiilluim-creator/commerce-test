from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_current_active_user, get_db_session
from models.database import Store, User
from services.rgpd_export import export_store_data

router = APIRouter()

@router.post("/export", summary="Export all GDPR-relevant data for the current store")
async def export_gdpr_data(
    current_user: User = Depends(get_current_active_user),
    db_session: AsyncSession = Depends(get_db_session)
):
    if not current_user.store_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not associated with a store")

    store = await db_session.get(Store, current_user.store_id)
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")

    zip_data = await export_store_data(store, db_session)

    return StreamingResponse(
        io.BytesIO(zip_data),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=gdpr_export_{store.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
        }
    )
