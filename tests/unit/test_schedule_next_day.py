import datetime

import pytest
from route_seed import (
    create_device,
    ensure_active_user,
    ensure_admin_user,
    set_admin_session,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from scheduler import logic, model


def _add_schedule_entry(
    device_id: str, date: datetime.date, template: str = "A"
) -> None:
    email = f"{template.lower()}@example.com"
    inst = model.db.session.scalars(select(model.Inst)).first()
    if inst is None:
        inst = model.Inst(id="I001", label="Test Inst", active=True)
        model.db.session.add(inst)
        model.db.session.flush()

    ensure_active_user(template, email, template)
    user = model.db.session.scalars(
        select(model.User).where(model.User.addr == email)
    ).first()
    assert user is not None
    model.db.session.add(
        model.ScheduleEntry(
            device=device_id,
            template=None,
            date=date,
            dow=date.weekday(),
            hour=8,
            group="DEV",
            user=user.id,
            orig_group="DEV",
            orig_inst=inst.id,
            modified_by="test-admin",
        )
    )


@pytest.mark.route
def test_next_schedule_day_logic(route_app_context):
    device_id, _ = create_device()
    _add_schedule_entry(device_id, datetime.date(2026, 1, 5), template="A1")
    _add_schedule_entry(device_id, datetime.date(2026, 1, 8), template="A2")
    _add_schedule_entry(device_id, datetime.date(2026, 1, 10), template="A3")
    model.db.session.flush()

    device = model.get(model.Device, device_id)
    assert device is not None

    assert logic.next_schedule_day(
        device, datetime.date(2026, 1, 7), 1
    ) == datetime.date(2026, 1, 8)
    assert logic.next_schedule_day(
        device, datetime.date(2026, 1, 9), -1
    ) == datetime.date(2026, 1, 8)
    assert logic.next_schedule_day(device, datetime.date(2026, 2, 1), 1) is None


def _seed_next_day_device(device_id: str) -> None:
    _add_schedule_entry(device_id, datetime.date(2026, 1, 5), template="A1")
    _add_schedule_entry(device_id, datetime.date(2026, 1, 8), template="A2")
    _add_schedule_entry(device_id, datetime.date(2026, 1, 10), template="A3")
    model.db.session.flush()


@pytest.mark.route
@pytest.mark.covers_route("/json/v1/device/<the_device>/schedule-next-day", "GET")
def test_device_schedule_next_day_endpoint(route_client, route_app_context):
    device_id, _ = create_device()
    _seed_next_day_device(device_id)
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get(
        f"/json/v1/device/{device_id}/schedule-next-day?start=2026-01-06&direction=1"
    )
    assert response.status_code == 200
    assert response.get_json() == {"date": "2026-01-08"}

    response = route_client.get(
        f"/json/v1/device/{device_id}/schedule-next-day?start=2025-01-01&direction=1"
    )
    assert response.status_code == 200
    assert response.get_json() == {"date": "2026-01-05"}


@pytest.mark.route
def test_device_schedule_next_day_endpoint_validates_params(
    route_client, route_app_context
):
    device_id, _ = create_device()
    _seed_next_day_device(device_id)
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get(
        f"/json/v1/device/{device_id}/schedule-next-day?start=bad&direction=1"
    )
    assert response.status_code == 400

    response = route_client.get(
        f"/json/v1/device/{device_id}/schedule-next-day?start=2026-01-06&direction=2"
    )
    assert response.status_code == 400

    response = route_client.get(
        f"/json/v1/device/{device_id}/schedule-next-day?start=2026-01-09&direction=-1"
    )
    assert response.status_code == 200
    assert response.get_json() == {"date": "2026-01-08"}


@pytest.mark.route
def test_device_schedule_next_day_without_start_returns_503_when_db_clock_unavailable(
    route_client, route_app_context, monkeypatch
):
    device_id, _ = create_device()
    _seed_next_day_device(device_id)
    ensure_admin_user()
    set_admin_session(route_client)

    def _raise():
        raise SQLAlchemyError("db clock unavailable")

    monkeypatch.setattr(logic, "db_now", _raise)

    response = route_client.get(
        f"/json/v1/device/{device_id}/schedule-next-day?direction=1"
    )
    assert response.status_code == 503
