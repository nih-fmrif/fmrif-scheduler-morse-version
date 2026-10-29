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
def test_rbac_mutate_batch_updates_group_pi_with_explicit_operation(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    old_pi = f"old-pi-{uuid.uuid4().hex[:6]}"
    new_pi = f"new-pi-{uuid.uuid4().hex[:6]}"
    ensure_active_user(old_pi, f"{old_pi}@example.com", old_pi)
    ensure_active_user(new_pi, f"{new_pi}@example.com", new_pi)
    set_group_membership(group_id, old_pi, approved=True, pi=True)
    set_group_membership(group_id, new_pi, approved=True, pi=False)

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
                        "kind": "group.pi.set",
                        "group": group_id,
                        "user": new_pi,
                        "expected_current_pi": old_pi,
                    }
                ]
            ),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is True
    assert payload["applied"] == 1
    assert model.get(model.PrimaryGroupMember, (group_id, old_pi)) is None
    assert model.get(model.PrimaryGroupMember, (group_id, new_pi)) is not None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_group_pi_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    old_pi = f"old-pi-{uuid.uuid4().hex[:6]}"
    new_pi = f"new-pi-{uuid.uuid4().hex[:6]}"
    ensure_active_user(old_pi, f"{old_pi}@example.com", old_pi)
    ensure_active_user(new_pi, f"{new_pi}@example.com", new_pi)
    set_group_membership(group_id, old_pi, approved=True, pi=True)
    set_group_membership(group_id, new_pi, approved=True, pi=False)

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
                        "kind": "group.pi.set",
                        "group": group_id,
                        "user": new_pi,
                        "expected_current_pi": "someone-else",
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
    assert model.get(model.PrimaryGroupMember, (group_id, old_pi)) is not None
    assert model.get(model.PrimaryGroupMember, (group_id, new_pi)) is None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_membership_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    user_id = f"mem-{uuid.uuid4().hex[:6]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    set_group_membership(group_id, user_id, approved=True, pi=False)

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
                        "user": user_id,
                        "member": True,
                        "approved": False,
                        "expected_member": True,
                        "expected_approved": False,
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    assert payload["applied"] == 0
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    row = model.get(model.GroupMember, (group_id, user_id))
    assert row is not None
    assert row.approved is not None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_rolls_back_all_changes_on_conflict(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    target_member = f"target-{uuid.uuid4().hex[:6]}"
    stale_member = f"stale-{uuid.uuid4().hex[:6]}"
    ensure_active_user(target_member, f"{target_member}@example.com", target_member)
    ensure_active_user(stale_member, f"{stale_member}@example.com", stale_member)
    set_group_membership(group_id, stale_member, approved=True, pi=False)

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
                        "user": target_member,
                        "member": True,
                        "approved": True,
                        "expected_member": False,
                        "expected_approved": False,
                    },
                    {
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": stale_member,
                        "member": True,
                        "approved": False,
                        "expected_member": True,
                        "expected_approved": False,
                    },
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    rolled_back_rows = [
        row for row in payload["results"] if row["status"] == "rolled_back"
    ]
    assert len(rolled_back_rows) == 1
    assert model.get(model.GroupMember, (group_id, target_member)) is None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_applies_group_meta_rows_without_cross_row_overwrite(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    group_row = model.get(model.Group, group_id)
    assert group_row is not None
    original_label = group_row.label
    original_description = group_row.description
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
                        "kind": "group.meta.set",
                        "group": group_id,
                        "label": "Meta Group One",
                        "expected_label": original_label,
                    },
                    {
                        "kind": "group.meta.set",
                        "group": group_id,
                        "description": "Updated metadata description",
                        "expected_description": original_description,
                    },
                ]
            ),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is True
    assert payload["applied"] == 2
    updated_group = model.get(model.Group, group_id)
    assert updated_group is not None
    assert updated_group.label == "Meta Group One"
    assert updated_group.description == "Updated metadata description"


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_group_meta_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    group_row = model.get(model.Group, group_id)
    assert group_row is not None
    original_label = group_row.label
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
                        "kind": "group.meta.set",
                        "group": group_id,
                        "label": "New Group Label",
                        "expected_label": "stale-label",
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
    fresh_group = model.get(model.Group, group_id)
    assert fresh_group is not None
    assert fresh_group.label == original_label
