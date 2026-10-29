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
    set_admin_session,
    set_group_membership,
    set_session_user,
)

from scheduler import logic, model
from scheduler.app import app

pytestmark = pytest.mark.route


@pytest.mark.covers_route("/device/<the_device>", "GET")
def test_device_get_for_dev_member_returns_ok():
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

    client = app.test_client()
    set_session_user(
        client,
        username="dev-route",
        email="dev-route@example.com",
        display_name="Dev Route",
        groups=["DEV"],
    )

    response = client.get(f"/device/{seeded_scanner_id()}")

    assert response.status_code == 200


def _create_template(device_id: str, template_id: str = "A", label: str = "Template A"):
    with app.app_context():
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
    with app.app_context():
        inst = model.Inst.query.filter(model.Inst.active).first()
        if inst is None:
            inst = model.Inst(
                id="I001",
                label="Test Institute",
                active=True,
            )
            model.db.session.add(inst)
            model.db.session.commit()
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
        model.db.session.commit()


@pytest.mark.covers_route("/device-add", "POST")
def test_device_add_post_creates_device():
    ensure_admin_user()
    client = app.test_client()
    set_admin_session(client)

    get_response = client.get("/device-add")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))
    suffix = uuid.uuid4().hex[:4]
    device_id = f"D{suffix}"
    device_label = f"Created {suffix}"

    post_response = client.post(
        "/device-add",
        data={
            "csrf_token": csrf_token,
            "id": device_id,
            "label": device_label,
            "description": f"Description {suffix}",
            "addr": "",
            "tech_addr": "",
            "med_addr": "",
            "train_addr": "",
            "active": "y",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(f"/device/{device_id}")
    with app.app_context():
        created = model.Device.query.get(device_id)
        assert created is not None
        assert created.label == device_label


@pytest.mark.covers_route("/device/<the_device>/edit", "POST")
def test_device_edit_post_updates_device():
    ensure_admin_user()
    device_id, _ = create_device()
    client = app.test_client()
    set_admin_session(client)

    get_response = client.get(f"/device/{device_id}/edit")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
        f"/device/{device_id}/edit",
        data={
            "csrf_token": csrf_token,
            "label": f"Updated {device_id}",
            "description": f"Updated Description {device_id}",
            "addr": "",
            "tech_addr": "",
            "med_addr": "",
            "train_addr": "",
            "active": "y",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(f"/device/{device_id}")
    with app.app_context():
        updated = model.Device.query.get(device_id)
        assert updated is not None
        assert updated.label == f"Updated {device_id}"


@pytest.mark.covers_route("/device/<the_device>/groups", "POST")
def test_device_groups_post_remove_unlinks_group():
    ensure_admin_user()
    device_id, _ = create_device()
    group_id = create_group(color="#335577", has_membership=True)
    with app.app_context():
        model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))
        model.db.session.commit()

    client = app.test_client()
    set_admin_session(client)
    get_response = client.get(f"/device/{device_id}/groups")
    html = get_response.get_data(as_text=True)
    csrf_token = extract_csrf_token(html)
    button_match = re.search(r'name="([^"]*remove)"', html)
    assert button_match is not None
    button_name = button_match.group(1)

    post_response = client.post(
        f"/device/{device_id}/groups",
        data={"csrf_token": csrf_token, button_name: "y"},
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(f"/device/{device_id}/groups")
    with app.app_context():
        assert model.DeviceGroup.query.get((device_id, group_id)) is None


@pytest.mark.covers_route("/device/<the_device>/groups/add", "POST")
def test_device_groups_add_post_links_group():
    ensure_admin_user()
    device_id, _ = create_device()
    group_id = create_group(color="#335577", has_membership=True)
    client = app.test_client()
    set_admin_session(client)

    get_response = client.get(f"/device/{device_id}/groups/add")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
        f"/device/{device_id}/groups/add",
        data={"csrf_token": csrf_token, "dept": group_id},
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(f"/device/{device_id}/groups")
    with app.app_context():
        assert model.DeviceGroup.query.get((device_id, group_id)) is not None


@pytest.mark.covers_route("/device/<the_device>/users/<the_user>", "POST")
def test_device_user_post_adds_special_permissions():
    ensure_admin_user()
    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )

    device_id, _ = create_device()
    user_id = f"dev{uuid.uuid4().hex[:4]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    set_group_membership("DEV", user_id, approved=True, pi=False)

    client = app.test_client()
    set_admin_session(client)
    get_response = client.get(f"/device/{device_id}/users/{user_id}")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
        f"/device/{device_id}/users/{user_id}",
        data={
            "csrf_token": csrf_token,
            "templates": "y",
            "cru": "add",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(f"/device/{device_id}/users")
    with app.app_context():
        entry = model.UserDevice.query.get((user_id, device_id))
        assert entry is not None
        assert entry.templates is True


@pytest.mark.covers_route("/device/<the_device>/templates/add", "POST")
def test_device_templates_add_post_creates_template():
    ensure_admin_user()
    device_id, _ = create_device()
    client = app.test_client()
    set_admin_session(client)

    get_response = client.get(f"/device/{device_id}/templates/add")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
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
    with app.app_context():
        tmpl = model.Template.query.get(("A", device_id))
        assert tmpl is not None


@pytest.mark.covers_route(
    "/device/<the_device>/templates/edit-metadata/<the_template>", "POST"
)
def test_device_templates_edit_metadata_post_updates_template():
    ensure_admin_user()
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    client = app.test_client()
    set_admin_session(client)

    get_response = client.get(f"/device/{device_id}/templates/edit-metadata/A")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
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
    with app.app_context():
        tmpl = model.Template.query.get(("A", device_id))
        assert tmpl is not None
        assert tmpl.label == "Updated Template"
        assert tmpl.hidden is True


@pytest.mark.covers_route("/device/<the_device>/templates", "POST")
def test_device_templates_apply_post_rejects_invalid_template_code():
    ensure_admin_user()
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    client = app.test_client()
    set_admin_session(client)

    get_response = client.get(f"/device/{device_id}/templates")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
        f"/device/{device_id}/templates",
        data={"csrf_token": csrf_token, "templates": "Z"},
        follow_redirects=False,
    )

    assert post_response.status_code == 200
    assert "invalid template code(s)" in post_response.get_data(as_text=True)
    with app.app_context():
        assert model.ScheduleEntry.query.filter_by(device=device_id).count() == 0


@pytest.mark.covers_route("/device/<the_device>/templates/edit/<the_template>", "POST")
def test_device_templates_edit_post_accepts_empty_diff_payload():
    ensure_admin_user()
    device_id, _ = create_device()
    _create_template(device_id, template_id="A", label="Template A")
    client = app.test_client()
    set_admin_session(client)

    get_response = client.get(f"/device/{device_id}/templates/edit/A")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
        f"/device/{device_id}/templates/edit/A",
        json={"csrf_token": csrf_token, "payload": {"diffs": []}},
        follow_redirects=False,
    )

    assert post_response.status_code == 200
    assert post_response.get_json() == {"saved": 0}


@pytest.mark.covers_route("/device/<the_device>", "POST")
def test_device_schedule_post_accepts_empty_diff_payload():
    ensure_admin_user()
    device_id, _ = create_device()
    client = app.test_client()
    set_admin_session(client)

    get_response = client.get(f"/device/{device_id}")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
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
