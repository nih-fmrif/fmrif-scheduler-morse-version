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
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import scheduler.logic.schedule_editor as logic
import scheduler.logic.templates as template_logic
from scheduler import model
from scheduler.logic.admin_issues import scheduler_save_failure_fingerprint
from scheduler.logic.schedule_editor import _clear_reference_data_cache

pytestmark = pytest.mark.route


def _schedule_entry_count(device_id: str) -> int:
    return int(
        model.db.session.scalar(
            select(func.count())
            .select_from(model.ScheduleEntry)
            .where(model.ScheduleEntry.device == device_id)
        )
        or 0
    )


def _schedule_entries_for_device(device_id: str) -> list[model.ScheduleEntry]:
    return (
        model.db.session.execute(
            select(model.ScheduleEntry).where(model.ScheduleEntry.device == device_id)
        )
        .unique()
        .scalars()
        .all()
    )


def _active_inst(*, exclude_id: str | None = None) -> model.Inst | None:
    statement = select(model.Inst).where(model.Inst.active).order_by(model.Inst.id)
    if exclude_id:
        statement = statement.where(model.Inst.id != exclude_id)
    return model.db.session.scalars(statement).first()


def _email_audit_rows(*criteria):
    statement = select(model.EmailAuditLog)
    for criterion in criteria:
        statement = statement.where(criterion)
    return model.db.session.scalars(statement).all()


class _Diag:
    def __init__(
        self,
        *,
        constraint_name=None,
        message_primary=None,
        message_detail=None,
        sqlstate=None,
    ):
        self.constraint_name = constraint_name
        self.message_primary = message_primary
        self.message_detail = message_detail
        self.sqlstate = sqlstate


class _Orig(Exception):
    def __init__(
        self,
        *,
        constraint_name=None,
        message_primary=None,
        message_detail=None,
        pgcode=None,
    ):
        super().__init__(message_primary or "database error")
        self.diag = _Diag(
            constraint_name=constraint_name,
            message_primary=message_primary,
            message_detail=message_detail,
            sqlstate=pgcode,
        )
        self.pgcode = pgcode


def _integrity_error(
    *,
    constraint_name=None,
    message_primary=None,
    message_detail=None,
    pgcode=None,
):
    return IntegrityError(
        "insert into tblsched ...",
        {},
        _Orig(
            constraint_name=constraint_name,
            message_primary=message_primary,
            message_detail=message_detail,
            pgcode=pgcode,
        ),
    )


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
    assert re.search(r'<input[^>]*name="start"[^>]*type="date"', body) is not None
    assert 'id="jump-open-picker"' in body


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
    assert re.search(r'<input[^>]*name="start"[^>]*type="date"', body) is not None
    assert 'id="jump-open-picker"' in body


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


@pytest.mark.covers_route("/device/<the_device>", "GET")
def test_device_get_filters_selection_groups_for_regular_editor(route_client):
    device_id = seeded_scanner_id()
    group_id = create_group()
    ensure_active_user("slot-editor", "slot-editor@example.com", "Slot Editor")
    set_group_membership(group_id, "slot-editor", approved=True, pi=False)

    if model.db.session.get(model.DeviceGroup, (device_id, group_id)) is None:
        model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))
        model.db.session.commit()
    _clear_reference_data_cache()

    set_session_user(
        route_client,
        username="slot-editor",
        email="slot-editor@example.com",
        display_name="Slot Editor",
        groups=[group_id],
    )

    response = route_client.get(f"/device/{device_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    match = re.search(
        r'<datalist id="selection-groups"[^>]*>(.*?)</datalist>',
        body,
        re.DOTALL,
    )
    assert match is not None
    options = match.group(1)
    assert f'value="{group_id}"' in options
    assert 'value="training"' not in options
    assert 'value="maint"' not in options


@pytest.mark.covers_route("/device/<the_device>", "GET")
def test_device_get_renders_hour_aligned_duration_presets(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get(f"/device/{seeded_scanner_id()}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "+1 hour" in body
    assert "+2 hours" in body
    assert "+3 hours" in body
    assert "+4 hours" in body
    assert "+30 min" not in body
    assert "+60 min" not in body
    assert "+90 min" not in body
    assert "+120 min" not in body
    assert '"slotMinutes"' not in body
    assert "data-duration-minutes=" not in body
    assert 'data-duration-slots="1"' in body
    assert 'data-duration-slots="2"' in body
    assert 'data-duration-slots="3"' in body
    assert 'data-duration-slots="4"' in body


def _create_template(device_id: str, template_id: str = "A", label: str = "Template A"):
    device = model.db.session.get(model.Device, device_id)
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
    created, _ = template_logic.create_template(fake_form, device)
    assert created is True


def _prepare_template_apply_data(
    device_id: str, template_id: str = "A"
) -> tuple[str, str, str]:
    group_id = create_group(color="#335577", has_membership=True)
    member_id = f"mem{uuid.uuid4().hex[:5]}"
    ensure_active_user(member_id, f"{member_id}@example.com", member_id)
    set_group_membership(group_id, member_id, approved=True, pi=False)
    inst = _active_inst()
    if inst is None:
        inst = model.Inst(
            id="I001",
            label="Test Institute",
            active=True,
        )
        model.db.session.add(inst)
        model.db.session.flush()
    model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))
    model.db.session.execute(
        text(
            """
            update tbltemplate
            set deptcode = :group_id,
                researchercode = :member_id,
                instcode = :inst_id
            where scannercode = :device_id
              and templatecode = :template_id
        """
        ),
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
    tmpl = model.db.session.get(model.Template, ("A", device_id))
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
    tmpl = model.db.session.get(model.Template, ("A", device_id))
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
    body = post_response.get_data(as_text=True)
    assert "invalid template code(s)" in body
    assert 'class="template-apply"' in body
    assert 'data-initial-state="dirty"' in body
    assert 'data-has-server-errors="1"' in body
    assert _schedule_entry_count(device_id) == 0


@pytest.mark.covers_route("/device/<the_device>/templates", "POST")
def test_device_templates_apply_post_preserves_required_field_error_state(
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
        data={"csrf_token": csrf_token, "templates": ""},
        follow_redirects=False,
    )

    assert post_response.status_code == 200
    body = post_response.get_data(as_text=True)
    assert "This field is required." in body
    assert 'class="template-apply"' in body
    assert 'data-initial-state="dirty"' in body
    assert 'data-has-server-errors="1"' in body
    assert _schedule_entry_count(device_id) == 0


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
        f"/device/{device_id}?start={template_logic.next_sunday().isoformat()}"
    )
    assert _schedule_entry_count(device_id) == 168


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
        for entry in _schedule_entries_for_device(device_id)
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
    assert 'data-template-state="blocking"' in body
    assert 'data-initial-state="pristine"' in body
    assert 'data-has-server-errors="0"' in body
    assert re.search(r"<button[^>]*data-js-submit[^>]*disabled", body) is not None


@pytest.mark.covers_route("/device/<the_device>", "GET")
def test_device_page_shows_templates_link_for_templates_only_device_permission(
    route_client,
):
    user_id = f"tmpl-route-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Template Route User")
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    model.db.session.add(
        model.UserDevice(
            user=user_id,
            device=device_id,
            templates=True,
            slot=False,
            tech=False,
            medical=False,
            training=False,
        )
    )
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Template Route User",
    )

    response = route_client.get(f"/device/{device_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f'href="/device/{device_id}/templates"' in body


@pytest.mark.covers_route("/device/<the_device>/templates", "GET")
def test_templates_only_device_permission_allows_template_routes(route_client):
    user_id = f"tmpl-only-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Template Only User")
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    model.db.session.add(
        model.UserDevice(
            user=user_id,
            device=device_id,
            templates=True,
            slot=False,
            tech=False,
            medical=False,
            training=False,
        )
    )
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Template Only User",
    )

    apply_response = route_client.get(f"/device/{device_id}/templates")
    edit_response = route_client.get(f"/device/{device_id}/templates/edit/A")

    assert apply_response.status_code == 200
    assert edit_response.status_code == 200


@pytest.mark.covers_route("/device/<the_device>/templates", "GET")
def test_slot_only_device_permission_does_not_allow_template_routes(route_client):
    user_id = f"slot-only-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Slot Only User")
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    model.db.session.add(
        model.UserDevice(
            user=user_id,
            device=device_id,
            templates=False,
            slot=True,
            tech=False,
            medical=False,
            training=False,
        )
    )
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Slot Only User",
    )

    response = route_client.get(f"/device/{device_id}/templates")

    assert response.status_code == 403


@pytest.mark.covers_route("/device/<the_device>/templates/edit/<the_template>", "GET")
def test_template_schedule_edit_describes_group_member_institute_fields(
    route_client,
):
    ensure_admin_user()
    set_admin_session(route_client)
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")

    response = route_client.get(f"/device/{device_id}/templates/edit/A")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Group is the schedulable group code." in body
    assert "Member must belong to that group." in body
    assert "Institute is stored separately on the template slot" in body


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
    existing_entries = _schedule_entry_count(device_id)

    get_response = route_client.get(f"/device/{device_id}/templates")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        f"/device/{device_id}/templates",
        data={"csrf_token": csrf_token, "templates": template_id},
        follow_redirects=False,
    )

    assert post_response.status_code == 200
    assert stale_summary in post_response.get_data(as_text=True)
    assert _schedule_entry_count(device_id) == existing_entries


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
    entry = model.db.session.get(model.TemplateEntry, entry_id)
    assert entry is not None
    replacement_inst = _active_inst(exclude_id=(entry.inst or ""))
    if replacement_inst is None:
        replacement_inst = _active_inst()
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
    if model.db.session.get(model.DeviceGroup, (device_id, group_id)) is None:
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
    assert payload.get("notifications") == [], payload
    assert slot_id in payload.get("id_map", {}), payload

    entry_id = int(payload["id_map"][slot_id])
    entry = model.db.session.get(model.ScheduleEntry, entry_id)
    assert entry is not None
    assert entry.device == device_id
    assert entry.date == slot_date
    assert entry.hour == 8
    assert entry.group == group_id
    assert entry.user == member_id
    audit_rows = _email_audit_rows(
        model.EmailAuditLog.action == "email.scheduler.notification"
    )
    assert audit_rows == []


@pytest.mark.covers_route("/device/<the_device>", "POST")
def test_device_schedule_post_persists_live_incident_for_unmapped_db_failure(
    route_client, route_app_context, monkeypatch
):
    ensure_admin_user()
    set_admin_session(route_client)

    device_id = seeded_scanner_id()
    group_id = create_group()
    member_id = "db-failure-member"
    ensure_active_user(member_id, "db-failure-member@example.com", "DB Failure Member")
    set_group_membership(group_id, member_id, approved=True, pi=False)
    slot_date = datetime.date(2035, 2, 2)
    slot_id = f"new-{slot_date.isoformat()}-08"
    if model.db.session.get(model.DeviceGroup, (device_id, group_id)) is None:
        model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))
        model.db.session.commit()
    _clear_reference_data_cache()

    get_response = route_client.get(
        f"/device/{device_id}?start={slot_date.isoformat()}&days=1"
    )
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    err = _integrity_error(
        constraint_name="tblsched_custom_debug_path",
        message_primary="violates custom schedule guard",
        message_detail="detail for admins only",
        pgcode="XX000",
    )
    real_commit = model.db.session.commit
    calls = {"count": 0}

    def flaky_commit():
        calls["count"] += 1
        if calls["count"] == 1:
            raise err
        return real_commit()

    monkeypatch.setattr(model.db.session, "commit", flaky_commit)

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
    assert payload["errors"][slot_id][0]["code"] == "database_rejected"
    assert payload["errors"][slot_id][0]["message"] == (
        "database rejected the change. refresh the schedule and retry. "
        "if it keeps happening, contact an administrator."
    )

    fingerprint = scheduler_save_failure_fingerprint(err)
    issue_key = f"scheduler-save-db:{device_id}:{fingerprint}"
    incident = model.db.session.get(model.NotificationIncident, issue_key)
    assert incident is not None
    assert incident.issue_type == "live.scheduler.db_error"
    assert incident.active is True
    assert incident.state == "open"
    assert "Constraint: tblsched_custom_debug_path" in incident.detail
