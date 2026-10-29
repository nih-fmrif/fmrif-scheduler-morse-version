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
    ensure_group,
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


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_is_atomic_on_validation_failure(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    device_id = seeded_scanner_id()
    user_id = f"rbacbatch{uuid.uuid4().hex[:5]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    operations = [
        {
            "kind": "device.group.set",
            "group": group_id,
            "device": device_id,
            "linked": True,
        },
        {
            "kind": "user.device.set",
            "user": user_id,
            "device": device_id,
            "templates": True,
            "slot": False,
            "tech": False,
            "medical": False,
            "training": False,
        },
    ]
    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(operations),
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    assert payload["atomic"] is True
    assert payload["applied"] == 0
    assert model.db.session.get(model.DeviceGroup, (device_id, group_id)) is None
    invalid = [row for row in payload["results"] if row["status"] == "invalid"]
    assert len(invalid) == 1
    assert "must target selected group" in invalid[0]["message"]


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_api_updates_user_device_permissions_and_audit_feed(
    route_client, route_app_context
):
    ensure_admin_user()
    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )

    user_id = f"rbacdev{uuid.uuid4().hex[:5]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    set_group_membership("DEV", user_id, approved=True, pi=False)
    device_id, _ = create_device()

    set_admin_session(route_client)
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    operations = [
        {
            "kind": "user.device.set",
            "user": user_id,
            "device": device_id,
            "templates": True,
            "slot": False,
            "tech": False,
            "medical": False,
            "training": True,
        }
    ]

    post_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "user",
            "entity": user_id,
            "operations": json.dumps(operations),
        },
        headers={"X-Forwarded-For": "198.51.100.7"},
    )
    assert post_response.status_code == 200
    payload = post_response.get_json()
    assert payload is not None
    assert payload["ok"] is True
    assert payload["atomic"] is True
    assert payload["applied"] == 1

    row = model.db.session.get(model.UserDevice, (user_id, device_id))
    assert row is not None
    assert row.templates is True
    assert row.training is True
    assert row.slot is False

    audit_response = route_client.get(
        f"/json/v1/rbac/audit?scope=user&entity={user_id}&limit=20"
    )
    assert audit_response.status_code == 200
    audit_payload = audit_response.get_json()
    assert audit_payload is not None
    assert audit_payload["scope"] == "user"
    assert audit_payload["selected"] == user_id
    matching = [
        event
        for event in audit_payload["events"]
        if event["action"] == "user.device.update"
        and event["where"] == f"/rbac?scope=user&entity={user_id}"
    ]
    assert len(matching) >= 1
    assert matching[0]["how"] == "rbac-explorer-batch"
    assert matching[0]["ip"] == "198.51.100.7"


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_updates_entity_active_state(route_client, route_app_context):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    device_id, _ = create_device()
    user_id = f"rbacactive{uuid.uuid4().hex[:4]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response_group = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [{"kind": "group.active.set", "group": group_id, "active": False}]
            ),
        },
    )
    assert response_group.status_code == 200
    payload_group = response_group.get_json()
    assert payload_group is not None
    assert payload_group["ok"] is True
    assert payload_group["applied"] == 1
    group = model.db.session.get(model.Group, group_id)
    assert group is not None
    assert group.active is False

    response_device = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "device",
            "entity": device_id,
            "operations": json.dumps(
                [{"kind": "device.active.set", "device": device_id, "active": False}]
            ),
        },
    )
    assert response_device.status_code == 200
    payload_device = response_device.get_json()
    assert payload_device is not None
    assert payload_device["ok"] is True
    assert payload_device["applied"] == 1
    device = model.db.session.get(model.Device, device_id)
    assert device is not None
    assert device.active is False

    response_user = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "user",
            "entity": user_id,
            "operations": json.dumps(
                [{"kind": "user.active.set", "user": user_id, "active": False}]
            ),
        },
    )
    assert response_user.status_code == 200
    payload_user = response_user.get_json()
    assert payload_user is not None
    assert payload_user["ok"] is True
    assert payload_user["applied"] == 1
    user = model.db.session.get(model.User, user_id)
    assert user is not None
    assert user.active is False

    response_special_group = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": "DEV",
            "operations": json.dumps(
                [{"kind": "group.active.set", "group": "DEV", "active": False}]
            ),
        },
    )
    assert response_special_group.status_code == 400
    payload_special_group = response_special_group.get_json()
    assert payload_special_group is not None
    assert payload_special_group["ok"] is False
    invalid_messages = [
        row["message"]
        for row in payload_special_group["results"]
        if row["status"] == "invalid"
    ]
    assert len(invalid_messages) == 1
    assert "special group cannot be deactivated" in invalid_messages[0]
