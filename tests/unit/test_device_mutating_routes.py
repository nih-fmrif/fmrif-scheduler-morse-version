import datetime
import re
import uuid
from types import SimpleNamespace

import pytest
from route_seed import (
    create_device,
    create_group,
    ensure_active_user,
    ensure_admin_user,
    ensure_group,
    extract_csrf_token,
    seeded_scanner_id,
    seeded_template_compatibility,
    set_admin_session,
    set_group_membership,
    set_session_user,
)
from sqlalchemy.exc import SQLAlchemyError

from scheduler import logic, model
from scheduler.logic.schedule_editor import _clear_reference_data_cache

pytestmark = pytest.mark.route


@pytest.mark.covers_route("/device/<the_device>", "GET")
def test_device_get_for_dev_member_returns_ok(route_client, route_app_context):
    ensure_group(
        "DEV",
        label="Development",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    ensure_active_user("dev-route", "dev-route@example.com", "Dev Route")
    set_group_membership("DEV", "dev-route", approved=True, pi=False)

    set_session_user(
        route_client,
        username="dev-route",
        email="dev-route@example.com",
        display_name="Dev Route",
        groups=["DEV"],
    )

    response = route_client.get(f"/device/{seeded_scanner_id()}")

    assert response.status_code == 200


@pytest.mark.covers_route("/device/<the_device>", "GET")
def test_device_get_defaults_jump_start_to_db_clock(route_client, monkeypatch):
    ensure_admin_user()
    set_admin_session(route_client)

    db_date = datetime.date(2035, 1, 2)
    monkeypatch.setattr(logic, "db_now", lambda: (db_date, 9, 30))

    response = route_client.get(f"/device/{seeded_scanner_id()}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    start_input = re.search(
        r'<input[^>]*name="start"[^>]*value="([0-9]{4}-[0-9]{2}-[0-9]{2})"',
        body,
    )
    assert start_input is not None
    assert start_input.group(1) == db_date.isoformat()


@pytest.mark.covers_route("/device/<the_device>", "GET")
def test_device_get_with_explicit_start_surfaces_db_clock_warning(
    route_client, monkeypatch
):
    ensure_admin_user()
    set_admin_session(route_client)

    chosen_date = datetime.date(2035, 2, 1)

    def _raise():
        raise SQLAlchemyError("db clock unavailable")

    monkeypatch.setattr(logic, "db_now", _raise)

    response = route_client.get(
        f"/device/{seeded_scanner_id()}?start={chosen_date.isoformat()}"
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Database time unavailable. Unable to refresh ET date right now." in body

    start_input = re.search(
        r'<input[^>]*name="start"[^>]*value="([0-9]{4}-[0-9]{2}-[0-9]{2})"',
        body,
    )
    assert start_input is not None
    assert start_input.group(1) == chosen_date.isoformat()


@pytest.mark.covers_route("/device/<the_device>", "GET")
def test_device_get_without_start_returns_503_when_db_clock_unavailable(
    route_client, monkeypatch
):
    ensure_admin_user()
    set_admin_session(route_client)

    def _raise():
        raise SQLAlchemyError("db clock unavailable")

    monkeypatch.setattr(logic, "db_now", _raise)

    response = route_client.get(f"/device/{seeded_scanner_id()}")
    assert response.status_code == 503
    assert "Database time unavailable. Unable to refresh ET date right now." in (
        response.get_data(as_text=True)
    )


def _create_template(device_id: str, template_id: str = "A", label: str = "Template A"):
    device = model.get(model.Device, device_id)
    assert device is not None
    fake_form = SimpleNamespace(
        id=SimpleNamespace(data=template_id),
        label=SimpleNamespace(data=label),
        description=SimpleNamespace(data=""),
        hidden=SimpleNamespace(data=False),
        clone_from=SimpleNamespace(data=""),
    )

    def populate(obj):
        obj.id = template_id
        obj.label = label
        obj.description = ""
        obj.hidden = False

    fake_form.populate_obj = populate
    created, _ = logic.create_template(fake_form, device)
    assert created is True


def _prepare_template_apply_data(
    device_id: str, template_id: str = "A"
) -> tuple[str, str, str]:
    group_id = create_group(color="#335577", has_membership=True)
    member_id = f"mem{uuid.uuid4().hex[:5]}"
    ensure_active_user(member_id, f"{member_id}@example.com", member_id)
    set_group_membership(group_id, member_id, approved=True, pi=False)
    inst = model.Inst.query.filter(model.Inst.active).first()
    if inst is None:
        inst = model.Inst(
            id="I001",
            label="Test Institute",
            active=True,
        )
        model.db.session.add(inst)
        model.db.session.flush()
    model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))
    model.execute(
        """
            update tbltemplate
            set deptcode = :group_id,
                researchercode = :member_id,
                instcode = :inst_id
            where scannercode = :device_id
              and templatecode = :template_id
        """,
        {
            "group_id": group_id,
            "member_id": member_id,
            "inst_id": inst.id,
            "device_id": device_id,
            "template_id": template_id,
        },
    )
    model.db.session.flush()
    return group_id, member_id, inst.id


def _add_existing_schedule_entry(
    device_id: str,
    date: datetime.date,
    group_id: str,
    member_id: str,
    inst_id: str,
) -> None:
    model.db.session.add(
        model.ScheduleEntry(
            device=device_id,
            template=None,
            date=date,
            dow=date.isoweekday() % 7,
            hour=8,
            group=group_id,
            user=member_id,
            orig_group=group_id,
            orig_inst=inst_id,
            modified_by="test-admin",
        )
    )
    model.db.session.flush()


@pytest.mark.covers_route("/device/<the_device>/templates/add", "POST")
def test_device_templates_add_post_creates_template(route_client, route_app_context):
    ensure_admin_user()
    device_id, _ = create_device()
    set_admin_session(route_client)

    get_response = route_client.get(f"/device/{device_id}/templates/add")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/device/{device_id}/templates/add",
        data={
            "csrf_token": csrf_token,
            "clone_from": "",
            "id": "A",
            "label": "Template A",
            "description": "",
            "hidden": "",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(
        f"/device/{device_id}/templates/edit/A"
    )
    tmpl = model.get(model.Template, ("A", device_id))
    assert tmpl is not None


@pytest.mark.covers_route(
    "/device/<the_device>/templates/edit-metadata/<the_template>", "POST"
)
def test_device_templates_edit_metadata_post_updates_template(
    route_client, route_app_context
):
    ensure_admin_user()
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    set_admin_session(route_client)

    get_response = route_client.get(f"/device/{device_id}/templates/edit-metadata/A")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/device/{device_id}/templates/edit-metadata/A",
        data={
            "csrf_token": csrf_token,
            "label": "Updated Template",
            "description": "Updated description",
            "hidden": "y",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(
        f"/device/{device_id}/templates/edit/A"
    )
    tmpl = model.get(model.Template, ("A", device_id))
    assert tmpl is not None
    assert tmpl.label == "Updated Template"
    assert tmpl.hidden is True


@pytest.mark.covers_route("/device/<the_device>/templates", "POST")
def test_device_templates_apply_post_rejects_invalid_template_code(
    route_client, route_app_context
):
    ensure_admin_user()
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    set_admin_session(route_client)

    get_response = route_client.get(f"/device/{device_id}/templates")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/device/{device_id}/templates",
        data={"csrf_token": csrf_token, "templates": "Z"},
        follow_redirects=False,
    )

    assert post_response.status_code == 200
    assert "invalid template code(s)" in post_response.get_data(as_text=True)
    assert model.ScheduleEntry.query.filter_by(device=device_id).count() == 0


@pytest.mark.covers_route("/device/<the_device>/templates", "POST")
def test_device_templates_apply_post_applies_valid_template(
    route_client, route_app_context
):
    ensure_admin_user()
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    _prepare_template_apply_data(device_id, template_id="A")
    set_admin_session(route_client)

    get_response = route_client.get(f"/device/{device_id}/templates")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/device/{device_id}/templates",
        data={"csrf_token": csrf_token, "templates": "A"},
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(
        f"/device/{device_id}?start={logic.next_sunday().isoformat()}"
    )
    assert model.ScheduleEntry.query.filter_by(device=device_id).count() == 168


@pytest.mark.covers_route("/device/<the_device>/templates", "POST")
def test_device_templates_apply_post_aligns_midweek_start_to_sunday(
    route_client, route_app_context
):
    ensure_admin_user()
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    group_id, member_id, inst_id = _prepare_template_apply_data(
        device_id, template_id="A"
    )
    _add_existing_schedule_entry(
        device_id,
        datetime.date(2026, 1, 27),
        group_id,
        member_id,
        inst_id,
    )
    set_admin_session(route_client)

    get_response = route_client.get(f"/device/{device_id}/templates")
    body = get_response.get_data(as_text=True)
    csrf_token = extract_csrf_token(body)

    assert get_response.status_code == 200
    assert (
        "template weeks always begin on Sunday, so template application will begin on Sunday 2026-02-01"
        in body
    )

    post_response = route_client.post(
        f"/device/{device_id}/templates",
        data={"csrf_token": csrf_token, "templates": "A"},
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(
        f"/device/{device_id}?start=2026-02-01"
    )

    templated_entries = [
        entry
        for entry in model.ScheduleEntry.query.filter_by(device=device_id).all()
        if entry.template is not None
    ]
    assert len(templated_entries) == 168
    assert min(entry.date for entry in templated_entries) == datetime.date(2026, 2, 1)
    assert max(entry.date for entry in templated_entries) == datetime.date(2026, 2, 7)


@pytest.mark.covers_route("/device/<the_device>/templates", "GET")
def test_seeded_template_apply_get_surfaces_repair_required_status(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)
    device_id, template_id, report = seeded_template_compatibility(
        archived=False,
        require_blocking=True,
        issue_code="legacy-member",
    )
    stale_summary = next(
        summary for summary in report["summary"] if "stale member" in summary.lower()
    )

    response = route_client.get(f"/device/{device_id}/templates")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "repair required" in body
    assert f"<strong>{template_id}</strong>" in body
    assert stale_summary in body


@pytest.mark.covers_route("/device/<the_device>/templates", "POST")
def test_seeded_template_apply_post_rejects_legacy_member_assignments(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)
    device_id, template_id, report = seeded_template_compatibility(
        archived=False,
        require_blocking=True,
        issue_code="legacy-member",
    )
    stale_summary = next(
        summary for summary in report["summary"] if "stale member" in summary.lower()
    )
    existing_entries = model.ScheduleEntry.query.filter_by(device=device_id).count()

    get_response = route_client.get(f"/device/{device_id}/templates")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/device/{device_id}/templates",
        data={"csrf_token": csrf_token, "templates": template_id},
        follow_redirects=False,
    )

    assert post_response.status_code == 200
    assert stale_summary in post_response.get_data(as_text=True)
    assert (
        model.ScheduleEntry.query.filter_by(device=device_id).count()
        == existing_entries
    )


@pytest.mark.covers_route("/device/<the_device>/templates/edit/<the_template>", "POST")
def test_seeded_template_edit_post_blocks_save_until_legacy_member_is_resolved(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)
    device_id, template_id, report = seeded_template_compatibility(
        archived=False,
        require_blocking=True,
        issue_code="legacy-member",
    )
    entry_id = next(
        int(issue["entry_id"])
        for issue in report["issues"]
        if issue["code"] == "legacy-member" and issue["entry_id"] is not None
    )
    entry = model.get(model.TemplateEntry, entry_id)
    assert entry is not None
    replacement_inst = (
        model.Inst.query.filter(model.Inst.active, model.Inst.id != (entry.inst or ""))
        .order_by(model.Inst.id)
        .first()
    )
    if replacement_inst is None:
        replacement_inst = (
            model.Inst.query.filter(model.Inst.active).order_by(model.Inst.id).first()
        )
    assert replacement_inst is not None

    get_response = route_client.get(f"/device/{device_id}/templates/edit/{template_id}")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/device/{device_id}/templates/edit/{template_id}",
        json={
            "csrf_token": csrf_token,
            "payload": {
                "diffs": [
                    {
                        "id": entry_id,
                        "institute": [entry.inst or "", replacement_inst.id],
                    }
                ]
            },
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 200
    payload = post_response.get_json()
    assert payload is not None
    assert "errors" in payload
    assert str(entry_id) in {str(key) for key in payload["errors"].keys()}
    assert any(
        "stale member" in summary.lower()
        for summary in payload.get("template_errors", [])
    )


@pytest.mark.covers_route("/device/<the_device>/templates/edit/<the_template>", "POST")
def test_device_templates_edit_post_accepts_empty_diff_payload(
    route_client, route_app_context
):
    ensure_admin_user()
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    set_admin_session(route_client)

    get_response = route_client.get(f"/device/{device_id}/templates/edit/A")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/device/{device_id}/templates/edit/A",
        json={"csrf_token": csrf_token, "payload": {"diffs": []}},
        follow_redirects=False,
    )

    assert post_response.status_code == 200
    assert post_response.get_json() == {"saved": 0}


@pytest.mark.covers_route("/device/<the_device>", "POST")
def test_device_schedule_post_accepts_empty_diff_payload(
    route_client, route_app_context
):
    ensure_admin_user()
    device_id, _ = create_device()
    set_admin_session(route_client)

    get_response = route_client.get(f"/device/{device_id}")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/device/{device_id}",
        json={
            "csrf_token": csrf_token,
            "payload": {"diffs": [], "notify": False},
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 200
    payload = post_response.get_json()
    assert payload is not None
    assert payload["saved"] == 0
    assert payload["notifications"] == []


@pytest.mark.covers_route("/device/<the_device>", "POST")
def test_device_schedule_post_creates_synthetic_slot_and_returns_id_map(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    device_id = seeded_scanner_id()
    group_id = create_group()
    member_id = "syn-slot-member"
    ensure_active_user(
        member_id, "syn-slot-member@example.com", "Synthetic Slot Member"
    )
    set_group_membership(group_id, member_id, approved=True, pi=False)
    slot_date = datetime.date(2035, 2, 1)
    slot_id = f"new-{slot_date.isoformat()}-08"
    if model.get(model.DeviceGroup, (device_id, group_id)) is None:
        model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))
        model.db.session.commit()
    _clear_reference_data_cache()

    get_response = route_client.get(
        f"/device/{device_id}?start={slot_date.isoformat()}&days=1"
    )
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/device/{device_id}?start={slot_date.isoformat()}&days=1",
        json={
            "csrf_token": csrf_token,
            "payload": {
                "diffs": [
                    {
                        "id": slot_id,
                        "date": slot_date.isoformat(),
                        "hour": 8,
                        "group": ["", group_id],
                        "member": ["", member_id],
                    }
                ],
                "notify": False,
            },
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 200
    payload = post_response.get_json()
    assert payload is not None
    assert payload.get("saved") == 1, payload
    assert isinstance(payload.get("notifications"), list), payload
    assert slot_id in payload.get("id_map", {}), payload

    entry_id = int(payload["id_map"][slot_id])
    entry = model.get(model.ScheduleEntry, entry_id)
    assert entry is not None
    assert entry.device == device_id
    assert entry.date == slot_date
    assert entry.hour == 8
    assert entry.group == group_id
    assert entry.user == member_id
