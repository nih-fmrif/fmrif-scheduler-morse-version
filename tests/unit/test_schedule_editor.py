import datetime
from types import SimpleNamespace

import pytest
from route_seed import ensure_active_user, ensure_group
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from scheduler import model
from scheduler.logic.schedule_editor import (
    SupportRequestDatalists,
    apply_scheduler_sr_diffs,
    off_hours,
    verify_scheduler_diffs,
)

pytestmark = pytest.mark.route


def test_off_hours_match_updated_daytime_band():
    assert off_hours() == {0, 1, 2, 3, 4, 5, 6, 23}


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


def _scheduler_perms(**overrides):
    base = {
        "edit": False,
        "edit_any": False,
        "tech": False,
        "medical": False,
        "training": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _seed_sched_entry(group_id: str, member_id: str) -> model.ScheduleEntry:
    entry = (
        model.db.session.execute(
            select(model.ScheduleEntry)
            .where(~model.ScheduleEntry.requests.any())
            .order_by(model.ScheduleEntry.id)
        )
        .unique()
        .scalars()
        .first()
    )
    if entry is None:
        entry = (
            model.db.session.execute(
                select(model.ScheduleEntry).order_by(model.ScheduleEntry.id)
            )
            .unique()
            .scalars()
            .first()
        )
        assert entry is not None
        for sr in list(entry.requests):
            model.db.session.delete(sr)
        model.db.session.flush()

    entry.group = group_id
    entry.user = member_id
    entry.orig_group = group_id
    entry.modified_by = "sched-admin"
    model.db.session.flush()
    return entry


def _seed_support_users():
    ensure_active_user("sched-admin", "sched-admin@example.com", "Scheduler Admin")
    ensure_active_user("sched-member", "sched-member@example.com", "Scheduler Member")
    ensure_active_user(
        "sched-support", "sched-support@example.com", "Scheduler Support"
    )
    ensure_group(
        "GRP1",
        label="Test Group",
        description="Test Group",
        color="#335577",
        active=True,
        has_membership=True,
    )
    admin = model.db.session.get(model.User, "sched-admin")
    member = model.db.session.get(model.User, "sched-member")
    support = model.db.session.get(model.User, "sched-support")
    assert admin is not None
    assert member is not None
    assert support is not None
    return admin, member, support


def _before_entry(entry: model.ScheduleEntry) -> tuple[datetime.date, int, int]:
    if entry.hour > 0:
        return entry.date, entry.hour - 1, 0
    return entry.date - datetime.timedelta(days=1), 23, 0


def test_verify_scheduler_diffs_creates_autoflush_safe_pending_support_requests(
    route_app_context,
):
    admin, member, _support = _seed_support_users()
    entry = _seed_sched_entry("GRP1", member.id)

    diffs = [
        {
            "id": entry.id,
            "train": {"requested": True},
            "tech": {"requested": True},
        }
    ]
    perms = _scheduler_perms(edit=True, edit_any=True, tech=True, training=True)
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
        *_before_entry(entry),
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


def test_support_only_user_can_fulfill_existing_future_support_request(
    route_app_context,
):
    admin, member, support_user = _seed_support_users()
    entry = _seed_sched_entry("GRP1", member.id)
    request = model.SupportRequest(
        schedid=entry.id,
        supportkind=1,
        filed_by=admin.id,
        modified_by=admin.id,
        approved=None,
        fulfilled_by=None,
        note="",
    )
    entry.requests.append(request)
    model.db.session.flush()

    xs, srs, _when, errors = verify_scheduler_diffs(
        [{"id": entry.id, "med": {"handler": ["", support_user.id]}}],
        [entry],
        _scheduler_perms(medical=True),
        SupportRequestDatalists(
            medical=[(support_user.id, support_user.label)],
            training=[],
            tech=[],
        ),
        *_before_entry(entry),
        [],
        {},
        support_user,
    )

    assert errors is None
    assert len(xs) == 1
    assert len(srs) == 1

    notes = apply_scheduler_sr_diffs(support_user, srs)
    assert notes == [
        {
            "id": entry.id,
            "kind": "medical",
            "state": "approved",
            "handler": support_user.id,
        }
    ]


@pytest.mark.parametrize(
    ("diff", "message"),
    [
        ({"med": {"requested": True}}, "booking edit access"),
        ({"med": {"handler": ["", "sched-support"]}}, "no active request to fulfill"),
    ],
)
def test_support_only_user_cannot_create_or_infer_new_support_requests(
    route_app_context, diff, message
):
    _admin, member, support_user = _seed_support_users()
    entry = _seed_sched_entry("GRP1", member.id)

    xs, srs, _when, errors = verify_scheduler_diffs(
        [{"id": entry.id, **diff}],
        [entry],
        _scheduler_perms(medical=True),
        SupportRequestDatalists(
            medical=[(support_user.id, support_user.label)],
            training=[],
            tech=[],
        ),
        *_before_entry(entry),
        [],
        {},
        support_user,
    )

    assert xs == []
    assert srs == []
    assert errors is not None
    assert message in errors[entry.id][0]["message"]
    model.db.session.rollback()


def test_booking_editor_without_support_permission_cannot_assign_handler(
    route_app_context,
):
    admin, member, support_user = _seed_support_users()
    entry = _seed_sched_entry("GRP1", member.id)
    request = model.SupportRequest(
        schedid=entry.id,
        supportkind=1,
        filed_by=admin.id,
        modified_by=admin.id,
        approved=None,
        fulfilled_by=None,
        note="",
    )
    entry.requests.append(request)
    model.db.session.flush()

    xs, srs, _when, errors = verify_scheduler_diffs(
        [{"id": entry.id, "med": {"handler": ["", support_user.id]}}],
        [entry],
        _scheduler_perms(edit=True),
        SupportRequestDatalists(
            medical=[(support_user.id, support_user.label)],
            training=[],
            tech=[],
        ),
        *_before_entry(entry),
        [("GRP1", "Test Group")],
        {"GRP1": [(member.id, member.label)]},
        member,
    )

    assert xs == []
    assert srs == []
    assert errors is not None
    assert "medical support access" in errors[entry.id][0]["message"]
