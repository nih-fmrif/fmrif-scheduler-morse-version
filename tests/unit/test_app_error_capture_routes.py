import re

import pytest
from route_seed import (
    ensure_active_user,
    ensure_admin_user,
    extract_csrf_token,
    set_admin_session,
    set_session_user,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from scheduler import logic, model
from scheduler.routes import rbac_mutations, rbac_routes

pytestmark = pytest.mark.route


def _app_error_count() -> int:
    return int(
        model.db.session.scalar(select(func.count()).select_from(model.AppErrorEvent))
        or 0
    )


def _disable_exception_propagation(client, monkeypatch) -> None:
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)
    monkeypatch.setitem(client.application.config, "TRAP_HTTP_EXCEPTIONS", False)


def test_unhandled_html_request_persists_app_error_event(route_client, monkeypatch):
    user_id = "error-html-user"
    ensure_active_user(user_id, f"{user_id}@example.com", "Error HTML User")
    set_session_user(
        route_client,
        username=user_id,
        email=f"{user_id}@example.com",
        display_name="Error HTML User",
    )
    _disable_exception_propagation(route_client, monkeypatch)

    def boom(*_args, **_kwargs):
        raise RuntimeError("home exploded access_token=secret-token")

    monkeypatch.setattr("scheduler.app.logic.get_devices", boom)

    response = route_client.get("/?access_token=secret-token")

    assert response.status_code == 500
    body = response.get_data(as_text=True)
    match = re.search(r"APP-ERR-[A-F0-9]{12}", body)
    assert match is not None

    row = model.db.session.scalars(
        select(model.AppErrorEvent).order_by(model.AppErrorEvent.id.desc())
    ).first()
    assert row is not None
    assert row.reference_id == match.group(0)
    assert row.actor == user_id
    assert row.where_path == "/"
    assert row.exception_type == "RuntimeError"
    assert row.request_context["request"]["query"]["access_token"] == "[REDACTED]"
    assert "secret-token" not in row.exception_message
    assert "secret-token" not in row.stack_trace


def test_unhandled_json_request_returns_reference_id(route_client, monkeypatch):
    ensure_admin_user()
    set_admin_session(route_client)
    _disable_exception_propagation(route_client, monkeypatch)

    def boom(*_args, **_kwargs):
        raise RuntimeError("json endpoint exploded code=secret-code")

    monkeypatch.setattr(rbac_routes, "_email_audit_search_field", boom)

    response = route_client.get(
        "/json/v1/email/audit?search_field=all",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 500
    payload = response.get_json()
    assert payload is not None
    assert payload["error"] == "Internal Server Error"
    reference_id = payload["reference_id"]

    row = model.db.session.scalars(
        select(model.AppErrorEvent).order_by(model.AppErrorEvent.id.desc())
    ).first()
    assert row is not None
    assert row.reference_id == reference_id
    assert row.actor == "test-admin"
    assert row.where_path == "/json/v1/email/audit"
    assert row.request_context["request"]["headers"]["accept"] == "application/json"
    assert "secret-code" not in row.exception_message


@pytest.mark.covers_route("/json/v1/app-errors", "GET")
def test_app_error_feed_returns_filtered_results_for_admin(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    logic.record_app_error_event(
        reference_id="APP-ERR-FEED0001",
        actor="test-admin",
        ip_addr="198.51.100.2",
        user_agent="pytest-agent",
        method="GET",
        where_path="/rbac",
        endpoint="rbac",
        status_code=500,
        exception_type="RuntimeError",
        exception_message="first failure",
        fingerprint="RuntimeError:first",
        request_context={"request": {"path": "/rbac"}},
        stack_trace="traceback one",
    )
    logic.record_app_error_event(
        reference_id="APP-ERR-FEED0002",
        actor="other-user",
        ip_addr="198.51.100.3",
        user_agent="pytest-agent",
        method="POST",
        where_path="/join",
        endpoint="join_form",
        status_code=500,
        exception_type="ValueError",
        exception_message="second failure",
        fingerprint="ValueError:second",
        request_context={"request": {"path": "/join"}},
        stack_trace="traceback two",
    )

    response = route_client.get(
        "/json/v1/app-errors?actor=test-admin&reference_id=APP-ERR-FEED0001"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["count"] == 1
    assert payload["events"][0]["reference_id"] == "APP-ERR-FEED0001"
    assert payload["events"][0]["actor"] == "test-admin"


def test_app_issues_page_renders_application_errors_section(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    logic.record_app_error_event(
        reference_id="APP-ERR-PAGE0001",
        actor="test-admin",
        ip_addr="198.51.100.4",
        user_agent="pytest-agent",
        method="GET",
        where_path="/app/issues",
        endpoint="app_issues",
        status_code=500,
        exception_type="RuntimeError",
        exception_message="page failure",
        fingerprint="RuntimeError:page",
        request_context={"request": {"path": "/app/issues"}},
        stack_trace="traceback page",
    )

    response = route_client.get("/app/issues")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Application errors" in body
    assert "APP-ERR-PAGE0001" in body


def test_not_found_does_not_persist_app_error_event(route_client):
    response = route_client.get("/missing-route")

    assert response.status_code == 404
    assert _app_error_count() == 0


def test_handled_500_response_does_not_persist_app_error_event(
    route_client, monkeypatch
):
    ensure_admin_user()
    set_admin_session(route_client)

    monkeypatch.setattr(
        rbac_mutations, "_rbac_parse_batch_operations", lambda _raw: [{"kind": "noop"}]
    )
    monkeypatch.setattr(
        rbac_mutations,
        "_rbac_validate_batch_operation",
        lambda operation, *, scope, entity: dict(operation),
    )
    monkeypatch.setattr(
        rbac_mutations,
        "_rbac_authorize_batch_operation",
        lambda _operation, _actor: None,
    )

    def fail_apply(*_args, **_kwargs):
        raise SQLAlchemyError("caught db failure")

    monkeypatch.setattr(rbac_mutations, "_rbac_apply_batch_operation", fail_apply)

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": "DEV",
            "operations": "[]",
        },
    )

    assert response.status_code == 500
    assert _app_error_count() == 0
