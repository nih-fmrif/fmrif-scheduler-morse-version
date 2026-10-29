import json

import pytest
from route_seed import ensure_admin_user, set_admin_session
from sqlalchemy import func, select

import scheduler.logic.csp_violation_events as logic
from scheduler import model

pytestmark = pytest.mark.route


@pytest.mark.covers_route("/csp-report", "POST")
def test_csp_report_route_ignores_legacy_payload(route_client):
    response = route_client.post(
        "/csp-report",
        data=json.dumps(
            {
                "csp-report": {
                    "document-uri": "https://app.example.test/auth/login",
                    "referrer": "https://app.example.test/",
                    "blocked-uri": "inline",
                    "violated-directive": "script-src-elem",
                    "effective-directive": "script-src-elem",
                    "original-policy": "default-src 'self'; script-src 'self'",
                    "source-file": "https://app.example.test/static/app.js",
                    "line-number": 12,
                    "column-number": 3,
                    "disposition": "enforce",
                    "status-code": 200,
                    "script-sample": "alert(1)",
                }
            }
        ),
        content_type="application/csp-report",
    )

    assert response.status_code == 204
    assert (
        model.db.session.scalar(
            select(func.count()).select_from(model.CspViolationEvent)
        )
        == 0
    )


def test_csp_report_route_persists_reporting_api_payload(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.post(
        "/csp-report",
        data=json.dumps(
            [
                {
                    "type": "csp-violation",
                    "age": 1,
                    "body": {
                        "documentURL": "https://app.example.test/device/TEST",
                        "blockedURL": "https://cdn.example.test/app.js",
                        "effectiveDirective": "script-src-elem",
                        "originalPolicy": "default-src 'self'; script-src 'self'",
                        "sourceFile": "https://app.example.test/static/app.js",
                        "lineNumber": 44,
                        "columnNumber": 2,
                        "disposition": "report",
                        "statusCode": 200,
                        "sample": "window.eval('x')",
                    },
                }
            ]
        ),
        content_type="application/reports+json",
    )

    assert response.status_code == 204
    row = model.db.session.scalars(
        select(model.CspViolationEvent).order_by(model.CspViolationEvent.id.desc())
    ).first()
    assert row is not None
    assert row.report_type == "csp-violation"
    assert row.actor == "test-admin"
    assert row.document_uri == "https://app.example.test/device/TEST"
    assert row.disposition == "report"


def test_app_issues_page_renders_csp_reports_section(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    logic.record_csp_violation_event(
        report_type="csp-violation",
        actor="test-admin",
        ip_addr="198.51.100.28",
        user_agent="pytest-agent",
        document_uri="https://app.example.test/auth/login",
        referrer="https://app.example.test/",
        blocked_uri="inline",
        violated_directive="style-src-elem",
        effective_directive="style-src-elem",
        original_policy="default-src 'self'; style-src 'self'",
        source_file="https://app.example.test/static/app.css",
        line_number=7,
        column_number=1,
        disposition="enforce",
        status_code=200,
        script_sample="body { color: red; }",
        report_body={"document-uri": "https://app.example.test/auth/login"},
    )

    response = route_client.get("/app/issues")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "CSP reports" in body
    assert "https://app.example.test/auth/login" in body
