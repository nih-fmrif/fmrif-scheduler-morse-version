import datetime

from sqlalchemy import select

from scheduler import logic, model


def test_record_csp_violation_event_persists_payload(app_context):
    stored = logic.record_csp_violation_event(
        report_type="csp-violation",
        actor="test-user",
        ip_addr="198.51.100.25",
        user_agent="pytest-agent",
        document_uri="https://app.example.test/auth/login",
        referrer="https://app.example.test/",
        blocked_uri="inline",
        violated_directive="script-src-elem",
        effective_directive="script-src-elem",
        original_policy="default-src 'self'; script-src 'self'",
        source_file="https://app.example.test/static/app.js",
        line_number=12,
        column_number=4,
        disposition="enforce",
        status_code=200,
        script_sample="alert(1)",
        report_body={"document-uri": "https://app.example.test/auth/login"},
    )

    assert stored is True
    row = model.db.session.scalars(
        select(model.CspViolationEvent).order_by(model.CspViolationEvent.id.desc())
    ).first()
    assert row is not None
    assert row.actor == "test-user"
    assert row.document_uri == "https://app.example.test/auth/login"
    assert row.violated_directive == "script-src-elem"
    assert row.report_body == {"document-uri": "https://app.example.test/auth/login"}


def test_record_csp_violation_event_prunes_expired_rows(app_context):
    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=logic.CSP_VIOLATION_EVENT_RETENTION_DAYS + 1
    )
    model.db.session.add(
        model.CspViolationEvent(
            report_type="csp-violation",
            actor="old-user",
            ip="198.51.100.26",
            user_agent="pytest-agent",
            document_uri="https://app.example.test/old",
            referrer=None,
            blocked_uri="inline",
            violated_directive="style-src-elem",
            effective_directive="style-src-elem",
            original_policy="default-src 'self'",
            source_file=None,
            line_number=None,
            column_number=None,
            disposition="enforce",
            status_code=200,
            script_sample=None,
            report_body={},
            occurred_at=old_time,
        )
    )
    model.db.session.commit()

    logic.record_csp_violation_event(
        report_type="csp-violation",
        actor="new-user",
        ip_addr="198.51.100.27",
        user_agent="pytest-agent",
        document_uri="https://app.example.test/new",
        referrer="",
        blocked_uri="inline",
        violated_directive="script-src-elem",
        effective_directive="script-src-elem",
        original_policy="default-src 'self'",
        source_file="",
        line_number=None,
        column_number=None,
        disposition="report",
        status_code=200,
        script_sample="",
        report_body={"document-uri": "https://app.example.test/new"},
    )

    assert (
        model.db.session.scalars(
            select(model.CspViolationEvent).where(
                model.CspViolationEvent.actor == "old-user"
            )
        ).first()
        is None
    )
    assert (
        model.db.session.scalars(
            select(model.CspViolationEvent).where(
                model.CspViolationEvent.actor == "new-user"
            )
        ).first()
        is not None
    )
