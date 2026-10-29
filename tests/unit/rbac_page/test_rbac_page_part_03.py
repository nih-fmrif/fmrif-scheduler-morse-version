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

pytestmark = [pytest.mark.route, pytest.mark.xdist_group("mailpit")]


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
def test_rbac_mutate_batch_returns_conflict_for_stale_device_group_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    device_id = seeded_scanner_id()
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "device.group.set",
                        "group": group_id,
                        "device": device_id,
                        "linked": True,
                        "expected_linked": True,
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    assert model.db.session.get(model.DeviceGroup, (device_id, group_id)) is None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_user_device_expected_state(
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
    set_admin_session(route_client)

    user_id = f"staleud{uuid.uuid4().hex[:5]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    set_group_membership("DEV", user_id, approved=True, pi=False)
    device_id, _ = create_device()
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
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "scope": "user",
            "entity": user_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "user.device.set",
                        "user": user_id,
                        "device": device_id,
                        "templates": True,
                        "slot": False,
                        "tech": False,
                        "medical": False,
                        "training": False,
                        "expected_templates": False,
                        "expected_slot": False,
                        "expected_tech": False,
                        "expected_medical": False,
                        "expected_training": False,
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    row = model.db.session.get(model.UserDevice, (user_id, device_id))
    assert row is not None
    assert row.templates is True


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_user_active_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    user_id = f"staleactive{uuid.uuid4().hex[:5]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "scope": "user",
            "entity": user_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "user.active.set",
                        "user": user_id,
                        "active": False,
                        "expected_active": False,
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    user_row = model.db.session.get(model.User, user_id)
    assert user_row is not None
    assert user_row.active is True


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_device_meta_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    device_id, _ = create_device()
    device_row = model.db.session.get(model.Device, device_id)
    assert device_row is not None
    original_label = device_row.label
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "scope": "device",
            "entity": device_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "device.meta.set",
                        "device": device_id,
                        "label": "Updated Device Label",
                        "expected_label": "stale-device-label",
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    fresh_device = model.db.session.get(model.Device, device_id)
    assert fresh_device is not None
    assert fresh_device.label == original_label


@pytest.mark.covers_route("/json/v1/rbac/explorer", "GET")
def test_rbac_explorer_api_returns_user_scope_payload_for_admin(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get("/json/v1/rbac/explorer?scope=user&entity=test-admin")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["scope"] == "user"
    assert payload["selected"] == "test-admin"
    assert isinstance(payload["scopes"], list)
    assert isinstance(payload["entities"], list)
    detail = payload["detail"]
    assert "summary" in detail
    assert "graph" in detail
    assert "matrices" in detail
    assert isinstance(detail["matrices"], list)


def test_rbac_explorer_hides_device_permissions_for_non_dev_user(route_client):
    ensure_admin_user()
    set_admin_session(route_client)
    user_id = f"nodev{uuid.uuid4().hex[:6]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)

    response = route_client.get(f"/json/v1/rbac/explorer?scope=user&entity={user_id}")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    detail = payload["detail"]

    matrices = detail.get("matrices", [])
    matrix_ids = {matrix.get("id") for matrix in matrices}
    assert "user-device-permissions-matrix" not in matrix_ids

    tables = detail.get("tables", [])
    table_titles = {table.get("title") for table in tables}
    assert "device-specific permissions" not in table_titles
    assert detail.get("graph", {}).get("targets") == []


def test_rbac_explorer_api_returns_guided_mutations(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    response = route_client.get(f"/json/v1/rbac/explorer?scope=group&entity={group_id}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    matrices = payload["detail"].get("matrices")
    assert isinstance(matrices, list)
    matrix_by_id = {matrix.get("id"): matrix for matrix in matrices}
    assert "group-metadata-matrix" in matrix_by_id
    metadata = matrix_by_id["group-metadata-matrix"]
    assert metadata.get("layout") == "keyvalue"
    assert any(row.get("field") == "active" for row in metadata.get("rows", []))
    assert payload["detail"].get("links") == []
