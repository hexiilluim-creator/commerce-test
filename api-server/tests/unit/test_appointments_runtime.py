from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from api.v1.appointments import AppointmentCreate, BusinessConfigUpdate, ServiceCreate, _apt_to_dict


def test_appointment_schemas_validate_required_and_defaults():
    service = ServiceCreate(name="Diagnostic")
    assert service.duration_min == 30 and service.is_active is True
    appointment = AppointmentCreate(scheduled_at=datetime(2026, 8, 14, 10, tzinfo=UTC), customer_phone="+21612345678")
    assert appointment.service_id is None
    config = BusinessConfigUpdate()
    assert config.default_slot_duration_min == 30
    with pytest.raises(ValidationError):
        AppointmentCreate(scheduled_at=datetime.now(UTC))


def test_appointment_to_dict_formats_timezone_and_optional_fields():
    scheduled = datetime(2026, 8, 14, 9, 30, tzinfo=UTC)
    appt = SimpleNamespace(id=3, customer_id=8, service_id=2, status=SimpleNamespace(value="confirmed"), scheduled_at=scheduled, duration_min=45, patient_name="Ali", notes=None, reminder_sent=False, created_at=None)
    result = _apt_to_dict(appt, ZoneInfo("Africa/Tunis"))
    assert result["id"] == 3
    assert result["status"] == "confirmed"
    assert result["scheduled_date"] == "2026-08-14"
    assert result["duration_min"] == 45


from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from api.v1.appointments import (
    AvailabilityRuleCreate, AppointmentStatusUpdate, BusinessConfigUpdate,
    create_service, create_availability, delete_service, delete_availability,
    get_config, update_config, get_slots, get_appointment,
    update_appointment_status, cancel_appointment, list_services,
)
from models.database import AppointmentStatus, BusinessType, DayOfWeek


@pytest.mark.asyncio
async def test_config_get_default_and_update_existing():
    store = SimpleNamespace(id=4)
    db = MagicMock()
    result = MagicMock(); result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)
    assert await get_config(store=store, db=db) == {"business_type": "ecommerce", "store_id": 4}

    cfg = SimpleNamespace(id=8, store_id=4, business_type=BusinessType.ECOMMERCE, service_category=None,
                          default_slot_duration_min=30, appointment_confirm_msg=None,
                          appointment_reminder_msg=None, booking_lead_time_hours=1,
                          max_appointments_per_day=None, address=None)
    result.scalar_one_or_none.return_value = cfg
    body = BusinessConfigUpdate(business_type=BusinessType.APPOINTMENTS, default_slot_duration_min=45)
    db.commit = AsyncMock(); db.refresh = AsyncMock()
    with patch.object(cfg, "business_type", BusinessType.ECOMMERCE):
        response = await update_config(body, store=store, db=db)
    assert response == {"ok": True, "business_type": "appointments"}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_services_list_create_and_not_found_mutations():
    store = SimpleNamespace(id=4)
    db = MagicMock()
    result = MagicMock(); result.scalars.return_value.all.return_value = [SimpleNamespace(id=1, name="Diag", description=None, duration_min=30, price=10, is_active=True)]
    db.execute = AsyncMock(return_value=result)
    assert (await list_services(store=store, db=db))[0]["name"] == "Diag"

    cfg_result = MagicMock(); cfg_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=cfg_result)
    db.flush = AsyncMock(); db.commit = AsyncMock(); db.refresh = AsyncMock()
    def add(obj):
        if hasattr(obj, "store_id") and obj.__class__.__name__ == "BusinessConfig": obj.id = 22
        elif hasattr(obj, "name"): obj.id = 9
    db.add.side_effect = add
    created = await create_service(ServiceCreate(name="Repair"), store=store, db=db)
    assert created["id"] == 9 and created["name"] == "Repair"

    missing = MagicMock(); missing.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=missing)
    with pytest.raises(HTTPException) as exc:
        await delete_service(77, store=store, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_availability_create_and_delete_not_found():
    store = SimpleNamespace(id=4)
    db = MagicMock(); cfg = MagicMock(); cfg.scalar_one_or_none.return_value = SimpleNamespace(id=3)
    db.execute = AsyncMock(return_value=cfg); db.commit = AsyncMock(); db.refresh = AsyncMock()
    def add_rule(obj):
        obj.id = 5
        if hasattr(obj, "day_of_week"):
            obj.day_of_week = DayOfWeek.MON
    db.add = MagicMock(side_effect=add_rule)
    created = await create_availability(AvailabilityRuleCreate(day_of_week="monday", start_time="09:00", end_time="12:00"), store=store, db=db)
    assert created["id"] == 5
    missing = MagicMock(); missing.scalar_one_or_none.return_value = None; db.execute = AsyncMock(return_value=missing)
    with pytest.raises(HTTPException) as exc:
        await delete_availability(88, store=store, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_slots_invalid_date_and_success_with_service():
    store = SimpleNamespace(id=4)
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await get_slots("bad-date", None, store=store, db=db)
    assert exc.value.status_code == 400
    service_result = MagicMock(); service_result.scalar_one_or_none.return_value = SimpleNamespace(id=2)
    db.execute = AsyncMock(return_value=service_result)
    with patch("api.v1.appointments.get_available_slots", new=AsyncMock(return_value=["09:00", "09:30"])):
        result = await get_slots("2026-08-15", 2, store=store, db=db)
    assert result == {"date": "2026-08-15", "slots": ["09:00", "09:30"], "count": 2}


@pytest.mark.asyncio
async def test_appointment_get_status_and_cancel_not_found():
    store = SimpleNamespace(id=4, timezone="Africa/Tunis")
    db = MagicMock(); missing = MagicMock(); missing.scalar_one_or_none.return_value = None; db.execute = AsyncMock(return_value=missing)
    with pytest.raises(HTTPException):
        await get_appointment(1, store=store, db=db)
    with pytest.raises(HTTPException):
        await update_appointment_status(1, AppointmentStatusUpdate(status=AppointmentStatus.CONFIRMED), store=store, db=db)
    with pytest.raises(HTTPException):
        await cancel_appointment(1, store=store, db=db)
