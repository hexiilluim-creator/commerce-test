"""
api/v1/appointments.py — Endpoints REST pour le module RDV
===========================================================
Routes:
  GET    /api/v1/appointments/             -> liste des RDV du store
  GET    /api/v1/appointments/{id}         -> détail d'un RDV
  POST   /api/v1/appointments/             -> créer un RDV (dashboard admin)
  PATCH  /api/v1/appointments/{id}/status  -> changer le statut
  DELETE /api/v1/appointments/{id}         -> annuler un RDV

  GET    /api/v1/appointments/services     -> liste des services
  POST   /api/v1/appointments/services     -> créer un service
  PUT    /api/v1/appointments/services/{id}-> modifier un service
  DELETE /api/v1/appointments/services/{id}-> supprimer un service

  GET    /api/v1/appointments/availability -> règles de dispo
  POST   /api/v1/appointments/availability -> créer une règle
  DELETE /api/v1/appointments/availability/{id} -> supprimer une règle

  GET    /api/v1/appointments/slots        -> créneaux libres pour une date
  GET    /api/v1/appointments/config       -> config BusinessConfig du store
  PUT    /api/v1/appointments/config       -> mettre à jour la config
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.auth import get_current_store
from models.database import (
    Appointment,
    AppointmentStatus,
    AvailabilityRule,
    BusinessConfig,
    BusinessType,
    Service,
    ServiceCategory,
    Store,
    get_db,
)
from services.appointment_agent import get_available_slots

router = APIRouter(prefix="/appointments", tags=["appointments"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ServiceCreate(BaseModel):
    name: str
    description: str | None = None
    duration_min: int = 30
    price: float | None = None
    is_active: bool = True


class ServiceUpdate(ServiceCreate):
    pass


class AvailabilityRuleCreate(BaseModel):
    day_of_week: str  # monday … sunday
    start_time: str   # "09:00"
    end_time: str     # "12:00"
    is_active: bool = True


class AppointmentCreate(BaseModel):
    service_id: int | None = None
    scheduled_at: datetime
    patient_name: str | None = None
    notes: str | None = None
    customer_phone: str


class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatus


class BusinessConfigUpdate(BaseModel):
    business_type: BusinessType = BusinessType.ECOMMERCE
    service_category: ServiceCategory | None = None
    default_slot_duration_min: int = 30
    appointment_confirm_msg: str | None = None
    appointment_reminder_msg: str | None = None
    booking_lead_time_hours: int = 1
    max_appointments_per_day: int | None = None
    address: str | None = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _apt_to_dict(appt: Appointment, tz: ZoneInfo) -> dict:
    dt = appt.scheduled_at.astimezone(tz)
    return {
        "id": appt.id,
        "customer_id": appt.customer_id,
        "service_id": appt.service_id,
        "status": appt.status.value,
        "scheduled_at": appt.scheduled_at.isoformat(),
        "scheduled_date": dt.strftime("%Y-%m-%d"),
        "scheduled_time": dt.strftime("%H:%M"),
        "duration_min": appt.duration_min,
        "patient_name": appt.patient_name,
        "notes": appt.notes,
        "reminder_sent": appt.reminder_sent,
        "created_at": appt.created_at.isoformat() if appt.created_at else None,
    }


# ─── Config endpoints ─────────────────────────────────────────────────────────

@router.get("/config")
async def get_config(
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(BusinessConfig).where(BusinessConfig.store_id == store.id))
    config = result.scalar_one_or_none()
    if not config:
        return {"business_type": "ecommerce", "store_id": store.id}
    return {
        "id": config.id,
        "store_id": config.store_id,
        "business_type": config.business_type.value,
        "service_category": config.service_category.value if config.service_category else None,
        "default_slot_duration_min": config.default_slot_duration_min,
        "appointment_confirm_msg": config.appointment_confirm_msg,
        "appointment_reminder_msg": config.appointment_reminder_msg,
        "booking_lead_time_hours": config.booking_lead_time_hours,
        "max_appointments_per_day": config.max_appointments_per_day,
        "address": config.address,
    }


@router.put("/config")
async def update_config(
    body: BusinessConfigUpdate,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(BusinessConfig).where(BusinessConfig.store_id == store.id))
    config = result.scalar_one_or_none()

    if not config:
        config = BusinessConfig(store_id=store.id)
        db.add(config)

    config.business_type = body.business_type
    config.service_category = body.service_category
    config.default_slot_duration_min = body.default_slot_duration_min
    config.appointment_confirm_msg = body.appointment_confirm_msg
    config.appointment_reminder_msg = body.appointment_reminder_msg
    config.booking_lead_time_hours = body.booking_lead_time_hours
    config.max_appointments_per_day = body.max_appointments_per_day
    config.address = body.address
    await db.commit()
    await db.refresh(config)
    return {"ok": True, "business_type": config.business_type.value}


# ─── Services endpoints ───────────────────────────────────────────────────────

@router.get("/services")
async def list_services(
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Service).where(Service.store_id == store.id).order_by(Service.id)
    )
    services = result.scalars().all()
    return [
        {
            "id": s.id, "name": s.name, "description": s.description,
            "duration_min": s.duration_min, "price": s.price, "is_active": s.is_active,
        }
        for s in services
    ]


@router.post("/services", status_code=201)
async def create_service(
    body: ServiceCreate,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    # Ensure BusinessConfig exists
    cfg_result = await db.execute(select(BusinessConfig).where(BusinessConfig.store_id == store.id))
    config = cfg_result.scalar_one_or_none()
    if not config:
        config = BusinessConfig(store_id=store.id)
        db.add(config)
        await db.flush()

    svc = Service(
        business_config_id=config.id,
        store_id=store.id,
        **body.model_dump(),
    )
    db.add(svc)
    await db.commit()
    await db.refresh(svc)
    return {"id": svc.id, "name": svc.name, "duration_min": svc.duration_min}


@router.put("/services/{service_id}")
async def update_service(
    service_id: int,
    body: ServiceUpdate,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Service).where(Service.id == service_id, Service.store_id == store.id)
    )
    svc = result.scalar_one_or_none()
    if not svc:
        raise HTTPException(404, "Service introuvable")
    for k, v in body.model_dump().items():
        setattr(svc, k, v)
    await db.commit()
    return {"ok": True}


@router.delete("/services/{service_id}", status_code=204)
async def delete_service(
    service_id: int,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Service).where(Service.id == service_id, Service.store_id == store.id)
    )
    svc = result.scalar_one_or_none()
    if not svc:
        raise HTTPException(404, "Service introuvable")
    await db.delete(svc)
    await db.commit()


# ─── Availability endpoints ───────────────────────────────────────────────────

@router.get("/availability")
async def list_availability(
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AvailabilityRule).where(AvailabilityRule.store_id == store.id)
        .order_by(AvailabilityRule.day_of_week, AvailabilityRule.start_time)
    )
    rules = result.scalars().all()
    return [
        {"id": r.id, "day_of_week": r.day_of_week.value, "start_time": r.start_time,
         "end_time": r.end_time, "is_active": r.is_active}
        for r in rules
    ]


@router.post("/availability", status_code=201)
async def create_availability(
    body: AvailabilityRuleCreate,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    cfg_result = await db.execute(select(BusinessConfig).where(BusinessConfig.store_id == store.id))
    config = cfg_result.scalar_one_or_none()
    if not config:
        config = BusinessConfig(store_id=store.id)
        db.add(config)
        await db.flush()

    rule = AvailabilityRule(
        business_config_id=config.id,
        store_id=store.id,
        day_of_week=body.day_of_week,
        start_time=body.start_time,
        end_time=body.end_time,
        is_active=body.is_active,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return {"id": rule.id, "day_of_week": rule.day_of_week.value}


@router.delete("/availability/{rule_id}", status_code=204)
async def delete_availability(
    rule_id: int,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AvailabilityRule).where(AvailabilityRule.id == rule_id, AvailabilityRule.store_id == store.id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Règle introuvable")
    await db.delete(rule)
    await db.commit()


# ─── Slots endpoint ───────────────────────────────────────────────────────────

@router.get("/slots")
async def get_slots(
    target_date: str = Query(..., description="Date ISO YYYY-MM-DD"),
    service_id: int | None = Query(None),
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    try:
        d = date.fromisoformat(target_date)
    except ValueError:
        raise HTTPException(400, "Format de date invalide (YYYY-MM-DD)")

    service = None
    if service_id:
        svc_result = await db.execute(
            select(Service).where(Service.id == service_id, Service.store_id == store.id)
        )
        service = svc_result.scalar_one_or_none()

    slots = await get_available_slots(db, store, d, service)
    return {"date": target_date, "slots": slots, "count": len(slots)}


# ─── Appointments CRUD ────────────────────────────────────────────────────────

@router.get("/")
async def list_appointments(
    status: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    tz = ZoneInfo(store.timezone or "Africa/Tunis")
    q = select(Appointment).where(Appointment.store_id == store.id)

    if status:
        try:
            q = q.where(Appointment.status == AppointmentStatus(status))
        except ValueError:
            raise HTTPException(400, f"Statut invalide: {status}")

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from).replace(tzinfo=tz)
            q = q.where(Appointment.scheduled_at >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to).replace(tzinfo=tz)
            q = q.where(Appointment.scheduled_at <= dt_to)
        except ValueError:
            pass

    q = q.order_by(Appointment.scheduled_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    appointments = result.scalars().all()
    return [_apt_to_dict(a, tz) for a in appointments]


@router.get("/{appointment_id}")
async def get_appointment(
    appointment_id: int,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.store_id == store.id,
        )
    )
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(404, "RDV introuvable")
    tz = ZoneInfo(store.timezone or "Africa/Tunis")
    return _apt_to_dict(appt, tz)


@router.post("/", status_code=201)
async def create_appointment(
    body: AppointmentCreate,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from models.database import Customer

    # Upsert customer
    stmt = pg_insert(Customer).values(
        store_id=store.id,
        whatsapp_phone=body.customer_phone,
        language=store.language or "fr",
    ).on_conflict_do_nothing(constraint="uq_customers_store_phone")
    await db.execute(stmt)
    await db.flush()
    cust = (await db.execute(
        select(Customer).where(Customer.store_id == store.id, Customer.whatsapp_phone == body.customer_phone)
    )).scalar_one()

    svc = None
    if body.service_id:
        svc = (await db.execute(select(Service).where(Service.id == body.service_id, Service.store_id == store.id))).scalar_one_or_none()

    appt = Appointment(
        store_id=store.id,
        customer_id=cust.id,
        service_id=body.service_id,
        status=AppointmentStatus.CONFIRMED,
        scheduled_at=body.scheduled_at,
        duration_min=svc.duration_min if svc else 30,
        patient_name=body.patient_name,
        notes=body.notes,
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)

    # Planifier rappel
    try:
        from datetime import timedelta

        from services.tasks import send_appointment_reminder
        reminder_time = body.scheduled_at - timedelta(hours=24)
        eta_secs = max(0, int((reminder_time - datetime.now(UTC)).total_seconds()))
        send_appointment_reminder.apply_async(args=[appt.id], countdown=eta_secs)
    except Exception as _exc:
        logger.warning("operation failed: %s", _exc)
        pass

    tz = ZoneInfo(store.timezone or "Africa/Tunis")
    return _apt_to_dict(appt, tz)


@router.patch("/{appointment_id}/status")
async def update_appointment_status(
    appointment_id: int,
    body: AppointmentStatusUpdate,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.store_id == store.id,
        )
    )
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(404, "RDV introuvable")
    appt.status = body.status
    await db.commit()
    return {"ok": True, "status": appt.status.value}


@router.delete("/{appointment_id}", status_code=204)
async def cancel_appointment(
    appointment_id: int,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.store_id == store.id,
        )
    )
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(404, "RDV introuvable")
    appt.status = AppointmentStatus.CANCELLED
    await db.commit()
