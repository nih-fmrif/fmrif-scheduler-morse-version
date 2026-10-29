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
    set_admin_session,
    set_group_membership,
    set_session_user,
)

from scheduler import logic, model

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


def _create_template(device_id: str, template_id: str = "A", label: str = "Template A"):
    device = model.Device.query.get(device_id)
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


def _prepare_template_apply_data(device_id: str, template_id: str = "A") -> None:
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
    model.db.session.execute(
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
    tmpl = model.Template.query.get(("A", device_id))
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
    tmpl = model.Template.query.get(("A", device_id))
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
