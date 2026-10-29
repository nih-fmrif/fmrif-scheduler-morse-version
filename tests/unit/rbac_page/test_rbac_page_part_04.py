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


def test_rbac_explorer_device_permissions_matrix_exposes_quick_add(route_client):
    ensure_admin_user()
    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    set_group_membership("DEV", "test-admin", approved=True, pi=False)
    set_admin_session(route_client)

    device_id, _ = create_device()
    response = route_client.get(
        f"/json/v1/rbac/explorer?scope=device&entity={device_id}"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["detail"].get("links") == []
    matrices = payload["detail"].get("matrices", [])
    matrix_by_id = {matrix.get("id"): matrix for matrix in matrices}
    assert "device-user-permissions-matrix" in matrix_by_id
    quick_add = matrix_by_id["device-user-permissions-matrix"].get("quick_add")
    assert isinstance(quick_add, dict)
    assert quick_add.get("label") == "+ add DEV user"
    operation = quick_add.get("operation")
    assert isinstance(operation, dict)
    assert operation.get("kind") == "user.device.set"
    assert operation.get("device") == device_id
    assert operation.get("expected_templates") is False
    assert operation.get("expected_slot") is False
    assert operation.get("expected_tech") is False
    assert operation.get("expected_medical") is False
    assert operation.get("expected_training") is False


def test_rbac_explorer_api_filters_inactive_entities_by_default(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    inactive_group_id = f"INACT{uuid.uuid4().hex[:4]}".upper()
    ensure_group(
        inactive_group_id,
        label=f"Inactive {inactive_group_id}",
        description=f"Inactive {inactive_group_id}",
        active=False,
    )

    inactive_device_id, _ = create_device()
    device_row = model.get(model.Device, inactive_device_id)
    assert device_row is not None
    device_row.active = False

    inactive_user_id = f"inusr{uuid.uuid4().hex[:5]}"
    ensure_active_user(
        inactive_user_id, f"{inactive_user_id}@example.com", inactive_user_id
    )
    user_row = model.get(model.User, inactive_user_id)
    assert user_row is not None
    user_row.active = False
    model.db.session.commit()

    default_response = route_client.get("/json/v1/rbac/explorer?scope=group&detail=0")
    assert default_response.status_code == 200
    default_payload = default_response.get_json()
    assert default_payload is not None
    assert default_payload["include_inactive"] is False
    default_ids = {entry["id"] for entry in default_payload["entities"]}
    assert inactive_group_id not in default_ids

    inclusive_response = route_client.get(
        "/json/v1/rbac/explorer?scope=group&detail=0&active=1"
    )
    assert inclusive_response.status_code == 200
    inclusive_payload = inclusive_response.get_json()
    assert inclusive_payload is not None
    assert inclusive_payload["include_inactive"] is True
    inclusive_ids = {entry["id"] for entry in inclusive_payload["entities"]}
    assert inactive_group_id in inclusive_ids

    default_devices_response = route_client.get(
        "/json/v1/rbac/explorer?scope=device&detail=0"
    )
    assert default_devices_response.status_code == 200
    default_devices_payload = default_devices_response.get_json()
    assert default_devices_payload is not None
    default_device_ids = {entry["id"] for entry in default_devices_payload["entities"]}
    assert inactive_device_id not in default_device_ids

    inclusive_devices_response = route_client.get(
        "/json/v1/rbac/explorer?scope=device&detail=0&active=1"
    )
    assert inclusive_devices_response.status_code == 200
    inclusive_devices_payload = inclusive_devices_response.get_json()
    assert inclusive_devices_payload is not None
    inclusive_device_ids = {
        entry["id"] for entry in inclusive_devices_payload["entities"]
    }
    assert inactive_device_id in inclusive_device_ids

    default_users_response = route_client.get(
        "/json/v1/rbac/explorer?scope=user&detail=0"
    )
    assert default_users_response.status_code == 200
    default_users_payload = default_users_response.get_json()
    assert default_users_payload is not None
    default_user_ids = {entry["id"] for entry in default_users_payload["entities"]}
    assert inactive_user_id not in default_user_ids

    inclusive_users_response = route_client.get(
        "/json/v1/rbac/explorer?scope=user&detail=0&active=1"
    )
    assert inclusive_users_response.status_code == 200
    inclusive_users_payload = inclusive_users_response.get_json()
    assert inclusive_users_payload is not None
    inclusive_user_ids = {entry["id"] for entry in inclusive_users_payload["entities"]}
    assert inactive_user_id in inclusive_user_ids

    hidden_detail_response = route_client.get(
        f"/json/v1/rbac/explorer?scope=group&entity={inactive_group_id}&entities=0&detail=1"
    )
    assert hidden_detail_response.status_code == 200
    hidden_detail_payload = hidden_detail_response.get_json()
    assert hidden_detail_payload is not None
    assert hidden_detail_payload["selected"] == ""
    assert hidden_detail_payload["detail"]["summary"]["title"] == "No groups found"

    visible_detail_response = route_client.get(
        f"/json/v1/rbac/explorer?scope=group&entity={inactive_group_id}&entities=0&detail=1&active=1"
    )
    assert visible_detail_response.status_code == 200
    visible_detail_payload = visible_detail_response.get_json()
    assert visible_detail_payload is not None
    assert visible_detail_payload["selected"] == inactive_group_id


def test_rbac_explorer_api_supports_detail_without_entity_list(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get(
        "/json/v1/rbac/explorer?scope=user&entity=test-admin&entities=0&detail=1"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["scope"] == "user"
    assert payload["selected"] == "test-admin"
    assert payload["entities"] == []
    assert payload["entities_included"] is False
    assert payload["detail"]["summary"]["subtitle"] == "user"


def test_rbac_explorer_api_forbidden_for_non_admin(route_client):
    user_id = "normal-user-rbac-api"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Normal User API")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Normal User API",
    )

    response = route_client.get("/json/v1/rbac/explorer?scope=group")

    assert response.status_code == 403


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_removes_device_group_link_for_admin(
    route_client, route_app_context, monkeypatch
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    device_id = seeded_scanner_id()
    model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))
    model.db.session.flush()

    events = _capture_rbac_events(monkeypatch)

    missing_csrf = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "action": "device.group.remove",
            "device": device_id,
            "group": group_id,
        },
    )
    assert missing_csrf.status_code == 400
    assert model.get(model.DeviceGroup, (device_id, group_id)) is not None

    get_response = route_client.get("/rbac")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

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
                        "kind": "device.group.set",
                        "device": device_id,
                        "group": group_id,
                        "linked": False,
                    }
                ]
            ),
        },
        headers={"X-Forwarded-For": "203.0.113.9"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is True
    assert payload["applied"] == 1
    assert model.get(model.DeviceGroup, (device_id, group_id)) is None
    assert len(events) == 1
    action, actor, where, how, what, source_ip = events[0]
    assert action == "device.group.remove"
    assert actor == "test-admin"
    assert where == f"/rbac?scope=device&entity={device_id}"
    assert how == "rbac-explorer-batch"
    assert f"device={device_id}" in what
    assert f"group={group_id}" in what
    assert source_ip == "203.0.113.9"
