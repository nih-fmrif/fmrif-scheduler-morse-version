import datetime

from sqlalchemy import select

from scheduler import logic, model


def test_record_app_error_event_persists_payload(app_context):
    stored = logic.record_app_error_event(
        reference_id="APP-ERR-UNIT0001",
        actor="test-user",
        ip_addr="198.51.100.9",
        user_agent="pytest-agent",
        method="GET",
        where_path="/test/path",
        endpoint="test.endpoint",
        status_code=500,
        exception_type="RuntimeError",
        exception_message="boom",
        fingerprint="RuntimeError:unit",
        request_context={"request": {"path": "/test/path"}},
        stack_trace="Traceback (most recent call last): ...",
    )

    assert stored is True
    row = model.db.session.scalars(
        select(model.AppErrorEvent)
        .where(model.AppErrorEvent.reference_id == "APP-ERR-UNIT0001")
        .order_by(model.AppErrorEvent.id.desc())
    ).first()
    assert row is not None
    assert row.actor == "test-user"
    assert row.where_path == "/test/path"
    assert row.request_context == {"request": {"path": "/test/path"}}


def test_record_app_error_event_prunes_expired_rows(app_context):
    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=logic.APP_ERROR_EVENT_RETENTION_DAYS + 1
    )
    model.db.session.add(
        model.AppErrorEvent(
            reference_id="APP-ERR-OLD0001",
            occurred_at=old_time,
            actor="old-user",
            ip="198.51.100.10",
            user_agent="pytest-agent",
            method="GET",
            where_path="/old/path",
            endpoint="old.endpoint",
            status_code=500,
            exception_type="ValueError",
            exception_message="stale",
            fingerprint="ValueError:old",
            request_context={},
            stack_trace="traceback",
        )
    )
    model.db.session.commit()

    logic.record_app_error_event(
        reference_id="APP-ERR-NEW0001",
        actor="new-user",
        ip_addr="198.51.100.11",
        user_agent="pytest-agent",
        method="POST",
        where_path="/new/path",
        endpoint="new.endpoint",
        status_code=500,
        exception_type="RuntimeError",
        exception_message="fresh",
        fingerprint="RuntimeError:new",
        request_context={"request": {"path": "/new/path"}},
        stack_trace="traceback",
    )

    assert (
        model.db.session.scalars(
            select(model.AppErrorEvent).where(
                model.AppErrorEvent.reference_id == "APP-ERR-OLD0001"
            )
        ).first()
        is None
    )
    assert (
        model.db.session.scalars(
            select(model.AppErrorEvent).where(
                model.AppErrorEvent.reference_id == "APP-ERR-NEW0001"
            )
        ).first()
        is not None
    )
