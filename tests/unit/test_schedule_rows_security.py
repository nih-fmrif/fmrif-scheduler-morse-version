import datetime
import html

import pytest
from route_seed import (
    ensure_admin_user,
    ensure_group,
    seeded_scanner_id,
    set_admin_session,
)
from sqlalchemy import select

from scheduler import model

pytestmark = pytest.mark.route


@pytest.mark.covers_route("/json/v1/device/<the_device>/schedule-rows", "GET")
def test_schedule_rows_escapes_html_like_values(route_client, route_app_context):
    ensure_admin_user()
    set_admin_session(route_client)

    device_id = seeded_scanner_id()
    ensure_group(
        "DEV", label="Development", description="Development Group", color="#111111"
    )
    ensure_group(
        "<img/>", label="<img/>", description="Malicious Group", color="#111111"
    )

    malicious_user = "<x onerror=1>"
    malicious_group = "<img/>"

    if model.db.session.get(model.User, malicious_user) is None:
        model.db.session.add(
            model.User(
                id=malicious_user,
                label="malicious",
                addr="malicious@example.com",
            )
        )

    inst = model.db.session.scalars(select(model.Inst).where(model.Inst.active)).first()
    if inst is None:
        inst = model.Inst(
            id="I999",
            label="Test Inst",
            active=True,
        )
        model.db.session.add(inst)

    target_date = datetime.date(2099, 12, 31)

    model.db.session.add(
        model.ScheduleEntry(
            device=device_id,
            template=None,
            date=target_date,
            dow=target_date.weekday(),
            hour=8,
            group=malicious_group,
            user=malicious_user,
            orig_group="DEV",
            orig_inst=inst.id,
            modified_by="test-admin",
        )
    )
    model.db.session.flush()

    response = route_client.get(
        f"/json/v1/device/{device_id}/schedule-rows?start={target_date.isoformat()}&days=1&hours=8"
    )
    assert response.status_code == 200

    payload = response.get_json()
    assert payload is not None
    rows = payload["rows"]
    assert len(rows) == 1
    assert rows[0]["hour"] == 8
    cell = rows[0]["cells"][0]
    assert html.escape(malicious_user) in cell
    assert html.escape(malicious_group) in cell
    assert malicious_user not in cell
    assert malicious_group not in cell
    assert "<entry-cell" in cell
