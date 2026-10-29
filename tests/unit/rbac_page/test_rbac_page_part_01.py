# ruff: noqa: F401
import datetime
import json
import re
import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest
from mailpit_api import (
    clear_mailpit_messages,
    get_mailpit_message,
    mailpit_available,
    mailpit_config_from_env,
    wait_for_mailpit_message,
)
from route_seed import (
    create_device,
    create_group,
    ensure_active_user,
    ensure_admin_user,
    ensure_dev_pi_user,
    ensure_group,
    ensure_group_pi_user,
    extract_csrf_token,
    seeded_scanner_id,
    set_admin_session,
    set_group_membership,
    set_session_user,
)

import scheduler.logic.rbac_audit_support as logic
import scheduler.message as scheduler_message
from scheduler import model
from scheduler.routes import rbac_routes

pytestmark = pytest.mark.route


def _capture_rbac_events(
    monkeypatch,
) -> list[tuple[str, str, str, str, str, str]]:
    events: list[tuple[str, str, str, str, str, str]] = []

    def capture(
        action: str,
        actor: str,
        where: str,
        how: str,
        what: str,
        source_ip: str = "",
    ) -> None:
        events.append((action, actor, where, how, what, source_ip))

    monkeypatch.setattr(logic, "log_rbac_audit_event", capture)
    return events


def _require_mailpit():
    cfg = mailpit_config_from_env()
    if cfg is None:
        pytest.skip(
            "Mailpit API config missing. Set MAILPIT__PORT or MAILPIT_API_BASE_URL."
        )
    if not mailpit_available(cfg):
        pytest.skip(f"Mailpit API not reachable at {cfg.api_base_url}.")
    return cfg


def _run_notification_scan(route_client, *, query: str = "") -> None:
    page = route_client.get(f"/app/issues{query}")
    assert page.status_code == 200
    csrf_token = extract_csrf_token(page.get_data(as_text=True))
    response = route_client.post(
        "/app/issues/notifications/scan",
        data={
            "csrf_token": csrf_token,
            "return_query": query.lstrip("?"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302


@contextmanager
def _route_mail_config(route_app, **mail_updates) -> Iterator[None]:
    original_mail_config = {
        "MAIL_SERVER": route_app.config.get("MAIL_SERVER"),
        "MAIL_PORT": route_app.config.get("MAIL_PORT"),
        "MAIL_USE_TLS": route_app.config.get("MAIL_USE_TLS"),
        "MAIL_USE_SSL": route_app.config.get("MAIL_USE_SSL"),
        "MAIL_SUPPRESS_SEND": route_app.config.get("MAIL_SUPPRESS_SEND"),
        "MAIL_DEFAULT_SENDER": route_app.config.get("MAIL_DEFAULT_SENDER"),
    }
    route_app.config.update(**mail_updates)
    scheduler_message.mailer.init_app(route_app)
    try:
        yield
    finally:
        route_app.config.update(**original_mail_config)
        scheduler_message.mailer.init_app(route_app)


@pytest.mark.covers_route("/rbac", "GET")
def test_rbac_page_renders_for_admin(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get("/rbac")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "RBAC Explorer" in body
    assert "Explorer Controls" in body
    assert "Relationship Map" in body
    assert "find entity" in body
    assert "view by" in body
    assert "include inactive" in body
    assert "entity" in body
    assert "+ add group" in body
    assert "+ add device" in body
    assert "Review And Update" in body


@pytest.mark.parametrize(
    ("path", "expects_json"),
    [
        ("/rbac?profile=1", False),
        ("/json/v1/rbac/explorer?scope=group&detail=0&profile=1", True),
        (
            "/json/v1/rbac/explorer?scope=group&entity=admin&detail=1&profile=1",
            True,
        ),
    ],
)
def test_rbac_profile_headers_capture_metrics(route_client, path, expects_json):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get(path)
    assert response.status_code == 200

    duration_ms = float(response.headers["X-RBAC-Profile-Duration-Ms"])
    sql_queries = int(response.headers["X-RBAC-Profile-SQL-Queries"])
    payload_bytes = int(response.headers["X-RBAC-Profile-Payload-Bytes"])
    assert duration_ms >= 0.0
    assert sql_queries >= 0
    assert payload_bytes > 0

    if expects_json:
        payload = response.get_json()
        assert isinstance(payload, dict)
    else:
        assert "RBAC Explorer" in response.get_data(as_text=True)


def test_rbac_page_forbidden_for_non_admin(route_client):
    user_id = "normal-user-rbac"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Normal User")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Normal User",
    )

    response = route_client.get("/rbac")

    assert response.status_code == 403


def test_rbac_page_renders_for_group_pi_of_non_dev_group(route_client):
    group_id = create_group()
    user_id = f"gpi{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, user_id)
    set_group_membership(group_id, user_id, approved=True, pi=True)

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name=user_id,
        groups=[group_id],
    )

    response = route_client.get("/rbac")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "RBAC Explorer" in body
    assert "Explorer Controls" in body
    assert "RBAC Audit" not in body
    assert 'class="rbac-audit-panel"' not in body


def test_rbac_page_renders_for_dev_pi(route_client):
    user_id, email = ensure_dev_pi_user(user_id=f"dpi{uuid.uuid4().hex[:6]}")
    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name=user_id,
        groups=["DEV"],
    )

    response = route_client.get("/rbac")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "RBAC Explorer" in body
    assert "Explorer Controls" in body
    assert "RBAC Audit" not in body
    assert 'class="rbac-audit-panel"' not in body


def test_rbac_explorer_limits_scope_and_entities_for_group_pi_of_non_dev_group(
    route_client,
):
    group_id = create_group()
    linked_device_id, _ = create_device()
    unlinked_device_id, _ = create_device()
    model.db.session.add(model.DeviceGroup(device=linked_device_id, group=group_id))
    model.db.session.flush()

    user_id = f"gpi{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, user_id)
    set_group_membership(group_id, user_id, approved=True, pi=True)

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name=user_id,
        groups=[group_id],
    )

    response = route_client.get("/json/v1/rbac/explorer?scope=device&detail=0&active=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["scope"] == "group"
    assert payload["include_inactive"] is False
    scopes = {scope["id"] for scope in payload["scopes"]}
    assert scopes == {"group"}
    entities = payload["entities"]
    ids = {entity["id"] for entity in entities}
    assert group_id in ids
    assert linked_device_id not in ids
    assert unlinked_device_id not in ids


def test_rbac_explorer_includes_all_active_devices_for_dev_pi(route_client):
    active_device_a, _ = create_device()
    active_device_b, _ = create_device()
    inactive_device_id, _ = create_device()
    inactive_device = model.db.session.get(model.Device, inactive_device_id)
    assert inactive_device is not None
    inactive_device.active = False
    model.db.session.add(inactive_device)
    model.db.session.flush()

    user_id, email = ensure_dev_pi_user(user_id=f"dpi{uuid.uuid4().hex[:6]}")
    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name=user_id,
        groups=["DEV"],
    )

    response = route_client.get("/json/v1/rbac/explorer?scope=device&detail=0&active=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["scope"] == "device"
    assert payload["include_inactive"] is False
    scopes = {scope["id"] for scope in payload["scopes"]}
    assert scopes == {"group", "device"}
    entities = payload["entities"]
    ids = {entity["id"] for entity in entities}
    assert active_device_a in ids
    assert active_device_b in ids
    assert inactive_device_id not in ids


def test_rbac_explorer_allows_device_detail_for_unlinked_active_device_for_dev_pi(
    route_client,
):
    managed_group = create_group()
    linked_device_id, _ = create_device()
    unlinked_device_id, _ = create_device()
    model.db.session.add(
        model.DeviceGroup(device=linked_device_id, group=managed_group)
    )
    model.db.session.flush()

    user_id, email = ensure_dev_pi_user(user_id=f"dpi{uuid.uuid4().hex[:6]}")
    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name=user_id,
        groups=["DEV"],
    )

    response = route_client.get(
        f"/json/v1/rbac/explorer?scope=device&entity={unlinked_device_id}&detail=1&active=1"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["scope"] == "device"
    assert payload["selected"] == unlinked_device_id
    entities = payload["entities"]
    ids = {entity["id"] for entity in entities}
    assert linked_device_id in ids
    assert unlinked_device_id in ids


def test_rbac_explorer_blocks_user_scope_for_dev_pi(route_client):
    user_id, email = ensure_dev_pi_user(user_id=f"dpi{uuid.uuid4().hex[:6]}")
    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name=user_id,
        groups=["DEV"],
    )

    response = route_client.get("/json/v1/rbac/explorer?scope=user&detail=0&active=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["scope"] == "group"
    scopes = {scope["id"] for scope in payload["scopes"]}
    assert scopes == {"group", "device"}


def test_rbac_mutate_batch_for_group_pi_of_non_dev_group_can_approve_managed_group_membership(
    route_client, route_app_context
):
    group_id = create_group()
    manager_id, manager_email = ensure_group_pi_user(group_id)
    member_id = f"mem{uuid.uuid4().hex[:6]}"
    ensure_active_user(member_id, f"{member_id}@example.com", member_id)
    device_id = seeded_scanner_id()

    set_session_user(
        route_client,
        username=manager_id,
        email=manager_email,
        display_name=manager_id,
        groups=[group_id],
    )

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    pending_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": member_id,
                        "member": True,
                        "approved": False,
                    }
                ]
            ),
        },
    )
    assert pending_response.status_code == 200
    member_row = model.db.session.get(model.GroupMember, (group_id, member_id))
    assert member_row is not None
    assert member_row.approved is None

    approval_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": member_id,
                        "member": True,
                        "approved": True,
                    }
                ]
            ),
        },
    )
    assert approval_response.status_code == 200
    approval_payload = approval_response.get_json()
    assert approval_payload is not None
    assert approval_payload["ok"] is True
    assert approval_payload["applied"] == 1
    member_row = model.db.session.get(model.GroupMember, (group_id, member_id))
    assert member_row is not None
    assert member_row.approved is not None

    blocked_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "device.group.set",
                        "group": group_id,
                        "device": device_id,
                        "linked": True,
                    }
                ]
            ),
        },
    )
    assert blocked_response.status_code == 403
    blocked_payload = blocked_response.get_json()
    assert blocked_payload is not None
    assert blocked_payload["ok"] is False
    assert "Permission denied" in blocked_payload["message"]


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_rejects_membership_pi_field(route_client, route_app_context):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    pi_owner = f"pi-owner-{uuid.uuid4().hex[:6]}"
    unrelated_member = f"member-{uuid.uuid4().hex[:6]}"
    stable_member = f"stable-{uuid.uuid4().hex[:6]}"
    ensure_active_user(pi_owner, f"{pi_owner}@example.com", pi_owner)
    ensure_active_user(
        unrelated_member, f"{unrelated_member}@example.com", unrelated_member
    )
    ensure_active_user(stable_member, f"{stable_member}@example.com", stable_member)
    set_group_membership(group_id, pi_owner, approved=True, pi=True)
    set_group_membership(group_id, stable_member, approved=True, pi=False)

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": unrelated_member,
                        "member": True,
                        "approved": True,
                    },
                    {
                        # Membership updates no longer accept pi.
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": stable_member,
                        "member": True,
                        "approved": True,
                        "pi": True,
                    },
                ]
            ),
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    invalid_messages = [
        row["message"] for row in payload["results"] if row["status"] == "invalid"
    ]
    assert len(invalid_messages) >= 1
    assert any("no longer accepts pi" in msg for msg in invalid_messages)

    assert model.db.session.get(model.GroupMember, (group_id, unrelated_member)) is None
    assert (
        model.db.session.get(model.PrimaryGroupMember, (group_id, pi_owner)) is not None
    )
    assert (
        model.db.session.get(model.PrimaryGroupMember, (group_id, stable_member))
        is None
    )
