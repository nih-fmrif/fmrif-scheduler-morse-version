import re
import uuid

import pytest
from flask import g
from route_seed import (
    create_device,
    create_group,
    ensure_active_user,
    ensure_admin_user,
    ensure_group,
    set_group_membership,
    set_session_user,
)

from scheduler import model

pytestmark = pytest.mark.route


def _find_device_card(device_id: str, body: str) -> re.Match[str] | None:
    return re.search(
        rf'<a[^>]*href="/device/{re.escape(device_id)}"[^>]*>.*?</a>',
        body,
        flags=re.S,
    )


def _find_device_list_item(device_id: str, body: str) -> re.Match[str] | None:
    return re.search(
        rf'<li[^>]*>\s*<a[^>]*href="/device/{re.escape(device_id)}"[^>]*>.*?</a>\s*</li>',
        body,
        flags=re.S,
    )


def test_home_shows_technologist_join_form_link_for_eligible_dev_member(route_client):
    user_id = f"home-tech-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home Tech User")
    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    set_group_membership("DEV", user_id, approved=True, pi=False)

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Tech User",
    )

    response = route_client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "FMRIF Scheduler" in body
    assert 'data-home-section="devices"' in body
    assert 'data-home-section="groups"' in body
    assert "technologist join form" in body
    assert 'href="/join/tech"' in body
    assert 'href="/mailing-lists"' in body


def test_home_hides_technologist_join_form_link_for_non_dev_member(route_client):
    user_id = f"home-user-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home User")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home User",
    )

    response = route_client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-home-section="groups"' in body
    assert "technologist join form" not in body
    assert 'href="/mailing-lists"' in body


def test_home_hides_groups_link_for_inactive_user(route_client, route_app_context):
    user_id = f"home-inactive-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home Inactive User")
    user = model.db.session.get(model.User, user_id)
    assert user is not None
    user.active = False
    model.db.session.add(user)
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Inactive User",
    )

    response = route_client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Groups are available only to active users." in body
    assert 'href="/join"' not in body
    assert 'href="/mailing-lists"' in body


def test_header_shows_global_home_button(route_client):
    user_id = f"home-global-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home Global User")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Global User",
    )

    response = route_client.get("/mailing-lists")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'class="menu-action home-link"' in body
    assert "FMRIF scheduler" in body
    assert body.index('class="menu-action home-link"') < body.index(
        '<section class="login-info"'
    )


def test_header_home_button_uses_local_mri_icon_and_accessible_label(route_client):
    user_id = f"home-icon-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home Icon User")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Icon User",
    )

    response = route_client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert re.search(
        r'<a[^>]*class="menu-action home-link"[^>]*aria-label="Home"',
        body,
    )
    assert 'class="icon-home-mri"' in body
    assert 'class="home-link-label-compact"' in body


def test_header_user_menu_includes_theme_controls(route_client):
    user_id = f"home-theme-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home Theme User")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Theme User",
    )

    response = route_client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "data-theme-toggle" in body
    assert 'data-theme-value="system"' in body
    assert 'data-theme-value="light"' in body
    assert 'data-theme-value="dark"' in body
    assert "data-theme-status" in body


def test_home_shows_rbac_link_for_admin(route_client):
    ensure_admin_user()
    user_id = "test-admin"
    email = f"{user_id}@example.com"

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="RBAC Admin User",
    )

    response = route_client.get("/")
    body = response.get_data(as_text=True)
    assert 'nav class="admin-links"' in body
    assert 'nav class="breadcrumb"' not in body
    assert body.index('href="/rbac"') < body.index('<details class="user-menu">')
    assert 'href="/rbac"' in body


def test_home_shows_admin_panel_link_for_admin(route_client):
    ensure_admin_user()
    user_id = "test-admin"
    email = f"{user_id}@example.com"

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="RBAC Admin User",
    )

    response = route_client.get("/")
    body = response.get_data(as_text=True)
    assert 'nav class="admin-links"' in body
    assert 'nav class="breadcrumb"' not in body
    assert body.index('href="/app/issues"') < body.index('<details class="user-menu">')
    assert 'href="/app/issues"' in body


def test_home_hides_rbac_link_for_non_admin(route_client, route_app_context):
    user_id = f"home-user-nonadmin-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home User")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home User",
    )

    response = route_client.get("/")
    body = response.get_data(as_text=True)
    assert 'href="/rbac"' not in body


def test_device_subpage_nav_escapes_device_label_html(route_client):
    ensure_admin_user()
    user_id = "test-admin"
    email = f"{user_id}@example.com"
    device_id, _ = create_device()
    evil_label = "<svg/onload=1>"
    device = model.db.session.get(model.Device, device_id)
    assert device is not None
    device.label = evil_label
    model.db.session.add(device)
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="RBAC Admin User",
    )

    response = route_client.get(f"/device/{device_id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<svg/onload=1>" not in body
    assert "&lt;svg/onload=1&gt;" in body
    assert "<sr-only> &lt;svg/onload=1&gt;</sr-only>" in body


def test_show_tech_join_form_probe_is_request_cached(monkeypatch, route_app_context):
    import scheduler.app as scheduler_app_module

    user_id = f"hct-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    user = model.User(id=user_id, label="Home Cache Tech User", addr=email, active=True)
    model.db.session.add(user)
    model.db.session.flush()

    call_count = 0

    def fake_show_tech_join_form(candidate):
        nonlocal call_count
        call_count += 1
        return candidate.id == user_id

    monkeypatch.setattr(
        scheduler_app_module.logic, "show_tech_join_form", fake_show_tech_join_form
    )

    with route_app_context.test_request_context("/join"):
        assert scheduler_app_module._cached_show_tech_join_form(user) is True
        assert scheduler_app_module._cached_show_tech_join_form(user) is True

    assert call_count == 1


def test_home_device_permissions_respects_auth_test_session_dev_pi(
    monkeypatch, route_app_context
):
    import scheduler.routes.core_routes as core_routes

    class DummyUser:
        def __init__(self, user_id: str):
            self.id = user_id
            self.active = True

    class DummyDevice:
        def __init__(self, device_id: str):
            self.id = device_id

    def unexpected_scalar(_statement):
        raise AssertionError("database DEV PI probe should not run")

    monkeypatch.setattr(core_routes.logic, "get_memberships", lambda _user: ["DEV"])
    monkeypatch.setattr(
        core_routes, "has_auth_test_session_pi_group", lambda _user, _group: True
    )
    monkeypatch.setattr(model.db.session, "scalar", unexpected_scalar)

    with route_app_context.test_request_context("/"):
        g.user = DummyUser("home-auth-test-dev-pi")
        permissions = core_routes._home_device_permissions([DummyDevice("scanner-a")])

    assert permissions == {"scanner-a": {"can_edit": True, "extra_privileges": []}}


def test_home_shows_read_only_indicator_for_devices_for_active_non_privileged_user(
    route_client,
):
    user_id = f"home-readonly-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home Read-only User")
    device_id, _ = create_device()
    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Read-only User",
    )

    response = route_client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    device_card = _find_device_card(device_id, body)
    assert device_card is not None
    card_html = device_card.group(0)
    assert 'data-device-permission="read-only"' in card_html
    assert "home-device-readonly" in card_html
    assert "home-device-perms" in card_html


def test_home_marks_device_with_group_edit_access_not_read_only(route_client):
    user_id = f"home-edit-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    group_id = create_group()
    ensure_active_user(user_id, email, "Home Edit User")
    set_group_membership(group_id, user_id, approved=True, pi=False)

    device_id, _ = create_device()
    model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Edit User",
    )

    response = route_client.get("/")
    body = response.get_data(as_text=True)
    assert response.status_code == 200

    device_card = _find_device_card(device_id, body)
    assert device_card is not None
    card_html = device_card.group(0)
    assert 'data-device-permission="editable"' in card_html
    assert "home-device-readonly" not in card_html


def test_home_shows_device_specific_privileges_for_read_only_user_devices(route_client):
    user_id = f"home-privs-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home Priv Device")
    device_id, _ = create_device()
    model.db.session.add(
        model.UserDevice(
            user=user_id,
            device=device_id,
            templates=False,
            slot=False,
            tech=True,
            medical=False,
            training=False,
        )
    )
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Priv Device",
    )

    response = route_client.get("/")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    device_card = _find_device_card(device_id, body)
    assert device_card is not None
    card_html = device_card.group(0)
    assert 'data-device-permission="read-only"' in card_html
    assert "home-device-readonly" in card_html
    assert "home-device-perms" in card_html
    assert "read-only" in card_html
    assert "technologist" in card_html


def test_home_shows_device_specific_privileges_for_editable_user_devices(route_client):
    user_id = f"home-edp-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    group_id = create_group()
    ensure_active_user(user_id, email, "Home Edit Priv Device")
    set_group_membership(group_id, user_id, approved=True, pi=False)

    device_id, _ = create_device()
    model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))
    model.db.session.add(
        model.UserDevice(
            user=user_id,
            device=device_id,
            templates=True,
            slot=True,
            tech=False,
            medical=True,
            training=False,
        )
    )
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Edit Priv Device",
    )

    response = route_client.get("/")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    device_card = _find_device_card(device_id, body)
    assert device_card is not None
    card_html = device_card.group(0)
    assert 'data-device-permission="editable"' in card_html
    assert "home-device-readonly" not in card_html
    assert "home-device-perms" in card_html
    assert "read-only" not in card_html
    assert "templates" in card_html
    assert "slot" in card_html
    assert "medical" in card_html


def test_home_hides_read_only_devices_by_default(route_client):
    user_id = f"hometog-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    group_id = create_group()
    ensure_active_user(user_id, email, "Home Toggle User")
    set_group_membership(group_id, user_id, approved=True, pi=False)

    editable_device_id, _ = create_device()
    readonly_device_id, _ = create_device()
    model.db.session.add(model.DeviceGroup(device=editable_device_id, group=group_id))
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Toggle User",
    )

    response = route_client.get("/")
    body = response.get_data(as_text=True)
    assert response.status_code == 200

    toggle = re.search(r'<input[^>]*id="home-show-readonly"[^>]*>', body)
    assert toggle is not None
    assert "checked" not in toggle.group(0)

    readonly_item = _find_device_list_item(readonly_device_id, body)
    assert readonly_item is not None
    readonly_html = readonly_item.group(0)
    assert 'data-home-readonly-device="true"' in readonly_html
    assert "hidden" in readonly_html

    editable_item = _find_device_list_item(editable_device_id, body)
    assert editable_item is not None
    editable_html = editable_item.group(0)
    assert 'data-home-readonly-device="true"' not in editable_html


def test_home_exposes_filter_and_show_more_configuration(route_client):
    ensure_admin_user()
    set_session_user(
        route_client,
        username="test-admin",
        email="test-admin@example.com",
        display_name="RBAC Admin User",
    )

    response = route_client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert 'id="home-device-search"' in body
    assert 'id="home-group-search"' in body
    assert 'id="home-devices-show-more"' in body
    assert 'id="home-groups-show-more"' in body
    assert 'data-home-filter-debounce-ms="200"' in body
    assert 'data-home-default-visible="5"' in body
    assert 'data-home-show-more-increment="10"' in body
    assert 'data-home-show-more-delay-ms="2000"' in body

    assert re.search(r'data-home-item-name="[^"]+"', body) is not None


def test_group_pi_probe_is_request_cached(monkeypatch, route_app_context):
    import scheduler.app as scheduler_app_module

    class DummyUser:
        def __init__(self, user_id: str):
            self.id = user_id
            self.active = True

    scalar_calls = {"count": 0}

    def fake_scalar(_statement):
        scalar_calls["count"] += 1
        return "group-pi-cache"

    monkeypatch.setattr(model.db.session, "scalar", fake_scalar)

    with route_app_context.test_request_context("/"):
        g.user = DummyUser("group-pi-cache")
        assert scheduler_app_module._rbac_user_is_group_pi(g.user) is True
        assert scheduler_app_module._rbac_user_is_group_pi(g.user) is True

    assert scalar_calls["count"] == 1


def test_group_pi_probe_uses_auth_test_session_before_db(
    monkeypatch, route_app_context
):
    import scheduler.routes.core_routes as core_routes

    class DummyUser:
        def __init__(self, user_id: str):
            self.id = user_id
            self.active = True

    def unexpected_scalar(_statement):
        raise AssertionError("database group PI probe should not run")

    monkeypatch.setattr(
        core_routes,
        "get_auth_test_session_pi_groups",
        lambda _user: {"DEV"},
    )
    monkeypatch.setattr(model.db.session, "scalar", unexpected_scalar)

    with route_app_context.test_request_context("/"):
        g.user = DummyUser("group-pi-auth-test")
        assert core_routes._rbac_user_is_group_pi(g.user) is True
