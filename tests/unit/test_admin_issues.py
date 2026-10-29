import pytest
from sqlalchemy.exc import IntegrityError

from scheduler import model
from scheduler.logic.admin_issues import (
    resolve_live_issue,
    scheduler_save_failure_issue_key,
    upsert_live_issue,
    upsert_scheduler_save_failure_issue,
)

pytestmark = pytest.mark.route


class _Diag:
    def __init__(
        self,
        *,
        constraint_name=None,
        message_primary=None,
        message_detail=None,
        sqlstate=None,
    ):
        self.constraint_name = constraint_name
        self.message_primary = message_primary
        self.message_detail = message_detail
        self.sqlstate = sqlstate


class _Orig(Exception):
    def __init__(
        self,
        *,
        constraint_name=None,
        message_primary=None,
        message_detail=None,
        pgcode=None,
    ):
        super().__init__(message_primary or "database error")
        self.diag = _Diag(
            constraint_name=constraint_name,
            message_primary=message_primary,
            message_detail=message_detail,
            sqlstate=pgcode,
        )
        self.pgcode = pgcode


def _integrity_error(
    *,
    constraint_name=None,
    message_primary=None,
    message_detail=None,
    pgcode=None,
):
    return IntegrityError(
        "insert into tblsched ...",
        {},
        _Orig(
            constraint_name=constraint_name,
            message_primary=message_primary,
            message_detail=message_detail,
            pgcode=pgcode,
        ),
    )


def test_upsert_live_issue_reopens_resolved_rows_and_counts_occurrences(
    route_app_context,
):
    issue_key = "live-test:one"

    created = upsert_live_issue(
        issue_key=issue_key,
        issue_type="scheduler.notification_delivery_failed",
        category="notifications",
        severity="critical",
        title="Initial title",
        detail="Initial detail",
        actor="tester",
    )
    assert created == issue_key
    model.db.session.commit()

    row = model.db.session.get(model.NotificationIncident, issue_key)
    assert row is not None
    assert row.active is True
    assert row.state == "open"
    assert row.occurrence_count == 1

    assert resolve_live_issue(issue_key, actor="tester", note="resolved in test")
    model.db.session.commit()

    row = model.db.session.get(model.NotificationIncident, issue_key)
    assert row is not None
    assert row.active is False
    assert row.state == "resolved"
    assert row.last_resolved_at is not None

    reopened = upsert_live_issue(
        issue_key=issue_key,
        issue_type="scheduler.notification_delivery_failed",
        category="notifications",
        severity="critical",
        title="Updated title",
        detail="Updated detail",
        actor="tester",
    )
    assert reopened == issue_key
    model.db.session.commit()

    row = model.db.session.get(model.NotificationIncident, issue_key)
    assert row is not None
    assert row.active is True
    assert row.state == "open"
    assert row.occurrence_count == 2
    assert row.title == "Updated title"
    assert row.detail == "Updated detail"


def test_upsert_scheduler_save_failure_issue_records_admin_detail(route_app_context):
    issue_key = upsert_scheduler_save_failure_issue(
        _integrity_error(
            constraint_name="tblsched_custom_debug_path",
            message_primary="violates custom schedule guard",
            message_detail="detail for admins only",
            pgcode="XX000",
        ),
        actor="tester",
        device_id="d",
        device_label="Device D",
        source="database",
        code="database_rejected",
        client_message="database rejected the change. refresh the schedule and retry.",
        href="/device/d",
    )
    assert issue_key is not None
    model.db.session.commit()

    row = model.db.session.get(model.NotificationIncident, issue_key)
    assert row is not None
    assert row.issue_type == "live.scheduler.db_error"
    assert row.category == "scheduler persistence"
    assert row.severity == "critical"
    assert row.title == "Scheduler save hit an unmapped database rejection"
    assert "Client-safe response:" in row.detail
    assert "SQLSTATE: XX000" in row.detail
    assert "Constraint: tblsched_custom_debug_path" in row.detail
    assert "Primary: violates custom schedule guard" in row.detail
    assert "Detail: detail for admins only" in row.detail
    assert row.issue_key == issue_key
    assert row.fingerprint
    assert row.issue_key == scheduler_save_failure_issue_key("d", row.fingerprint)
