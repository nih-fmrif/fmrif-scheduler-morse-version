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

import scheduler.message as scheduler_message
from scheduler import logic, model
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
def test_rbac_mutate_batch_updates_group_and_device_metadata(
    route_client, route_app_context, monkeypatch
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    device_id, _ = create_device()
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    events = _capture_rbac_events(monkeypatch)

    group_update = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.meta.set",
                        "group": group_id,
                        "label": "Meta Group",
                        "description": "Metadata Updated Group",
                        "addr": "meta-group@example.com",
                        "link": "https://example.org/group-meta",
                        "color": "#123456",
                        "inst": "",
                        "active": False,
                    }
                ]
            ),
        },
        headers={"X-Forwarded-For": "198.51.100.31"},
    )
    assert group_update.status_code == 200
    group_payload = group_update.get_json()
    assert group_payload is not None
    assert group_payload["ok"] is True
    assert group_payload["applied"] == 1
    group = model.Group.query.get(group_id)
    assert group is not None
    assert group.label == "Meta Group"
    assert group.description == "Metadata Updated Group"
    assert group.addr == "meta-group@example.com"
    assert group.link == "https://example.org/group-meta"
    assert group.color == "#123456"
    assert group.inst is None
    assert group.active is False

    device_update = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "device",
            "entity": device_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "device.meta.set",
                        "device": device_id,
                        "label": "Meta Device",
                        "description": "Updated device description",
                        "addr": "device@example.com",
                        "tech_addr": "tech@example.com",
                        "med_addr": "med@example.com",
                        "train_addr": "train@example.com",
                        "active": False,
                    }
                ]
            ),
        },
        headers={"X-Forwarded-For": "198.51.100.31"},
    )
    assert device_update.status_code == 200
    device_payload = device_update.get_json()
    assert device_payload is not None
    assert device_payload["ok"] is True
    assert device_payload["applied"] == 1
    device = model.Device.query.get(device_id)
    assert device is not None
    assert device.label == "Meta Device"
    assert device.description == "Updated device description"
    assert device.addr == "device@example.com"
    assert device.tech_addr == "tech@example.com"
    assert device.med_addr == "med@example.com"
    assert device.train_addr == "train@example.com"
    assert device.active is False

    assert any(
        action == "group.update"
        and where == f"/rbac?scope=group&entity={group_id}"
        and how == "rbac-explorer-batch"
        and source_ip == "198.51.100.31"
        for action, _actor, where, how, _what, source_ip in events
    )
    assert any(
        action == "device.update"
        and where == f"/rbac?scope=device&entity={device_id}"
        and how == "rbac-explorer-batch"
        and source_ip == "198.51.100.31"
        for action, _actor, where, how, _what, source_ip in events
    )


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_rejects_invalid_group_link_url(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)
    group_id = create_group()
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
                        "kind": "group.meta.set",
                        "group": group_id,
                        "label": "Meta Group",
                        "description": "Meta Group",
                        "addr": "",
                        "link": "not-a-url",
                        "color": "#123456",
                        "inst": "",
                    }
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
    assert len(invalid_messages) == 1
    assert "invalid URL for link" in invalid_messages[0]


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_creates_group_and_device(
    route_client, route_app_context, monkeypatch
):
    ensure_admin_user()
    set_admin_session(route_client)
    events = _capture_rbac_events(monkeypatch)

    pi_user = f"rbacpi{uuid.uuid4().hex[:5]}"
    ensure_active_user(pi_user, f"{pi_user}@example.com", pi_user)
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    new_group = f"RB{uuid.uuid4().hex[:8]}".upper()
    new_device = f"d{uuid.uuid4().hex[:4]}"

    group_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": "__create__",
            "operations": json.dumps(
                [
                    {
                        "kind": "group.create",
                        "group": new_group,
                        "label": f"Label {new_group}",
                        "description": f"Description {new_group}",
                        "pi": pi_user,
                        "addr": "",
                        "link": "",
                        "color": "#0f4c81",
                        "inst": "",
                        "active": True,
                    }
                ]
            ),
        },
        headers={"X-Forwarded-For": "198.51.100.88"},
    )
    assert group_response.status_code == 200
    group_payload = group_response.get_json()
    assert group_payload is not None
    assert group_payload["ok"] is True
    created_group = model.Group.query.get(new_group)
    assert created_group is not None
    assert created_group.label == f"Label {new_group}"
    membership = model.GroupMember.query.get((new_group, pi_user))
    assert membership is not None
    pi = model.PrimaryGroupMember.query.get((new_group, pi_user))
    assert pi is not None

    device_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "device",
            "entity": "__create__",
            "operations": json.dumps(
                [
                    {
                        "kind": "device.create",
                        "device": new_device,
                        "label": f"Label {new_device}",
                        "description": "Created from RBAC",
                        "addr": "device@example.com",
                        "tech_addr": "",
                        "med_addr": "",
                        "train_addr": "",
                        "active": True,
                    }
                ]
            ),
        },
        headers={"X-Forwarded-For": "198.51.100.88"},
    )
    assert device_response.status_code == 200
    device_payload = device_response.get_json()
    assert device_payload is not None
    assert device_payload["ok"] is True
    created_device = model.Device.query.get(new_device)
    assert created_device is not None
    assert created_device.label == f"Label {new_device}"

    assert any(
        action == "group.create"
        and where == f"/group/{new_group}"
        and how == "rbac-explorer-batch"
        and source_ip == "198.51.100.88"
        for action, _actor, where, how, _what, source_ip in events
    )
    assert any(
        action == "device.create"
        and where == f"/device/{new_device}"
        and how == "rbac-explorer-batch"
        and source_ip == "198.51.100.88"
        for action, _actor, where, how, _what, source_ip in events
    )
