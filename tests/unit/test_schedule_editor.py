from types import SimpleNamespace

import pytest
from route_seed import ensure_active_user, ensure_group
from sqlalchemy import inspect as sa_inspect

from scheduler import model
from scheduler.logic.schedule_editor import (
    SupportRequestDatalists,
    verify_scheduler_diffs,
)

pytestmark = pytest.mark.route


def _missing_required_fields(obj) -> list[str]:
    missing = []
    mapper = sa_inspect(type(obj))
    for attr in mapper.column_attrs:
        column = attr.columns[0]
        if column.primary_key or column.nullable:
            continue
        if (
            column.default is not None
            or column.server_default is not None
            or column.server_onupdate is not None
        ):
            continue
        if getattr(obj, attr.key) is None:
            missing.append(attr.key)
    return missing


def test_verify_scheduler_diffs_creates_autoflush_safe_pending_support_requests(
    route_app_context,
):
    ensure_active_user("sched-admin", "sched-admin@example.com", "Scheduler Admin")
    ensure_active_user("sched-member", "sched-member@example.com", "Scheduler Member")
    ensure_group(
        "GRP1",
        label="Test Group",
        description="Test Group",
        color="#335577",
        active=True,
        has_membership=True,
    )

    entry = (
        model.ScheduleEntry.query.filter(~model.ScheduleEntry.requests.any())
        .order_by(model.ScheduleEntry.id)
        .first()
    )
    if entry is None:
        entry = model.ScheduleEntry.query.order_by(model.ScheduleEntry.id).first()
        assert entry is not None
        for sr in list(entry.requests):
            model.db.session.delete(sr)
        model.db.session.flush()

    entry.group = "GRP1"
    entry.user = "sched-member"
    entry.orig_group = "GRP1"
    entry.modified_by = "sched-admin"
    model.db.session.flush()

    admin = model.User.query.get("sched-admin")
    member = model.User.query.get("sched-member")
    assert admin is not None
    assert member is not None

    diffs = [
        {
            "id": entry.id,
            "train": {"requested": True},
            "tech": {"requested": True},
        }
    ]
    perms = SimpleNamespace(edit_any=True)
    support = SupportRequestDatalists(
        medical=[],
        training=[(admin.id, admin.label)],
        tech=[(admin.id, admin.label)],
    )
    groups = [("GRP1", "Test Group")]
    members_of_groups = {"GRP1": [(member.id, member.label)]}

    xs, srs, when, errors = verify_scheduler_diffs(
        diffs,
        [entry],
        perms,
        support,
        entry.date,
        entry.hour,
        0,
        groups,
        members_of_groups,
        admin,
    )

    assert errors is None
    assert len(xs) == 1
    assert when[entry.id] == (False, entry.date, entry.hour)
    assert len(srs) == 2

    pending = list(model.db.session.new)
    assert pending
    assert all(isinstance(obj, model.SupportRequest) for obj in pending)
    assert {obj.supportkind for obj in pending} == {2, 3}
    assert all(obj.filed_by == admin.id for obj in pending)
    assert all(obj.modified_by == admin.id for obj in pending)

    missing_by_object = {
        f"{type(obj).__name__}:{getattr(obj, 'supportkind', '?')}": _missing_required_fields(
            obj
        )
        for obj in pending
    }
    assert missing_by_object == {key: [] for key in missing_by_object}

    model.db.session.flush()
