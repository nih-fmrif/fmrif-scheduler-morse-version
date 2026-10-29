from __future__ import annotations

import datetime
from collections import defaultdict
from functools import lru_cache
from typing import Dict, List, Optional, Set, Tuple

from flask_wtf import FlaskForm
from sqlalchemy import or_, select, text, union
from sqlalchemy.sql.functions import func
from wtforms import fields, validators

from scheduler import model

from ._schedule_editor_shared import Datalist, SupportRequestDatalists

_FMT_HOURS = {
    0: "Mid.",
    12: "Noon",
}
_OFF_HOURS = frozenset({*range(0, 7), 23})

for _i in range(1, 24):
    if _i == 12:
        continue
    _meridiem = "a" if _i < 12 else "p"
    _hour = _i if _i <= 12 else _i - 12
    _FMT_HOURS[_i] = f"{_hour}{_meridiem}m"


def schedule_for(
    device: model.Device, start: datetime.date, end: datetime.date
) -> List[model.ScheduleEntry]:
    entry_model = model.ScheduleEntry
    statement = (
        select(entry_model)
        .where(entry_model.device == device.id)
        .where(entry_model.date.between(start, end))
        .order_by(entry_model.date, entry_model.hour)
    )
    return model.db.session.execute(statement).unique().scalars().all()


def schedule_for_hours(
    device: model.Device, start: datetime.date, end: datetime.date, hours: List[int]
) -> List[model.ScheduleEntry]:
    entry_model = model.ScheduleEntry
    statement = (
        select(entry_model)
        .where(entry_model.device == device.id)
        .where(entry_model.date.between(start, end))
        .where(entry_model.hour.in_(hours))
        .order_by(entry_model.hour, entry_model.date)
    )
    return model.db.session.execute(statement).unique().scalars().all()


def schedule_exists_for(
    device: model.Device, start: datetime.date, end: datetime.date
) -> bool:
    entry_model = model.ScheduleEntry
    statement = (
        select(entry_model.id)
        .where(entry_model.device == device.id)
        .where(entry_model.date.between(start, end))
        .limit(1)
    )
    return model.db.session.execute(statement).first() is not None


def schedule_used_hours_for(
    device: model.Device, start: datetime.date, end: datetime.date
) -> Set[int]:
    entry_model = model.ScheduleEntry
    statement = (
        select(entry_model.hour)
        .where(entry_model.device == device.id)
        .where(entry_model.date.between(start, end))
        .distinct()
    )
    return set(model.db.session.execute(statement).scalars())


def group_schedule_entries(
    entries: List[model.ScheduleEntry],
) -> Tuple[List[str], List[List[model.ScheduleEntry]]]:
    days = set()
    header = []
    grouped_entries: List[List[model.ScheduleEntry]] = [[] for _ in range(24)]
    for entry in entries:
        if entry.date not in days:
            days.add(entry.date)
            header.append(fmt_date(entry.date, with_day=True))
        grouped_entries[entry.hour].append(entry)
    return header, grouped_entries


def group_template_entries(
    entries: List[model.TemplateEntry],
) -> List[List[model.TemplateEntry]]:
    grouped_entries: List[List[model.TemplateEntry]] = [[] for _ in range(24)]
    for entry in entries:
        grouped_entries[entry.hour].append(entry)
    return grouped_entries


def device_schedule_extreme_dates(
    device: model.Device,
) -> Tuple[Optional[datetime.date], Optional[datetime.date]]:
    entry_model = model.ScheduleEntry
    statement = select(func.min(entry_model.date), func.max(entry_model.date)).where(
        entry_model.device == device.id
    )
    first_date, last_date = model.db.session.execute(statement).one()
    return first_date, last_date


def next_schedule_day(
    device: model.Device, from_date: datetime.date, direction: int
) -> Optional[datetime.date]:
    entry_model = model.ScheduleEntry
    if direction == 1:
        statement = select(func.min(entry_model.date)).where(
            entry_model.device == device.id,
            entry_model.date > from_date,
        )
    else:
        statement = select(func.max(entry_model.date)).where(
            entry_model.device == device.id,
            entry_model.date < from_date,
        )

    return model.db.session.execute(statement).scalar()


def date_or_today(date: Optional[datetime.date]) -> datetime.date:
    if date is None:
        return db_now()[0]
    return date


def fmt_date(date: Optional[datetime.date], with_day: bool = False) -> str:
    if date is None:
        return ""
    fmt = "%Y-%m-%d"
    if with_day:
        fmt += " %a"
    return date.strftime(fmt)


def parse_date(value: str) -> Optional[datetime.date]:
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_days(days: str) -> Optional[int]:
    try:
        parsed_days = int(days)
        if not (0 < parsed_days < 32):
            return None
        return parsed_days
    except ValueError:
        return None


def end_date(date: datetime.date, days: int) -> datetime.date:
    return date + datetime.timedelta(days=days)


def user_datalist_entry(user_id: str, name: str) -> str:
    if name == "" or user_id == name:
        return user_id
    return f"{name} ({user_id})"


def get_device_from_schedid(entry_id) -> Optional[model.Device]:
    entry = model.db.session.get(model.ScheduleEntry, entry_id)
    if entry is None:
        return None
    return model.db.session.get(model.Device, entry.device)


def get_sched_log_entry(entry_id: int):
    log_entry = model.db.session.get(model.SchedLogEntry, entry_id)
    if log_entry is None:
        return None
    return log_entry.entries


def support_request_datalists(device: model.Device) -> SupportRequestDatalists:
    statement = (
        select(
            model.User.id,
            model.User.label,
            model.UserDevice.tech,
            model.UserDevice.medical,
            model.UserDevice.training,
        )
        .join(model.User, model.User.id == model.UserDevice.user)
        .where(model.User.active.is_(True))
        .where(model.UserDevice.device == device.id)
        .where(
            or_(
                model.UserDevice.tech.is_(True),
                model.UserDevice.medical.is_(True),
                model.UserDevice.training.is_(True),
            )
        )
        .order_by(model.User.label)
    )

    tech, med, train = [], [], []
    for user_id, name, is_tech, is_med, is_train in model.db.session.execute(
        statement
    ).all():
        pair = (user_id, user_datalist_entry(user_id, name))
        if is_tech:
            tech.append(pair)
        if is_med:
            med.append(pair)
        if is_train:
            train.append(pair)

    return SupportRequestDatalists(tech, med, train)


def all_member_datalists_by_group(device: model.Device) -> Dict[str, Datalist]:
    statement = (
        select(model.DeviceGroup.group, model.GroupMember.user, model.User.label)
        .join(model.Group, model.Group.id == model.DeviceGroup.group)
        .join(model.GroupMember, model.GroupMember.group == model.DeviceGroup.group)
        .join(model.User, model.User.id == model.GroupMember.user)
        .where(model.DeviceGroup.device == device.id)
        .where(model.GroupMember.approved.is_not(None))
        .where(model.Group.department.is_(True))
        .where(model.Group.active.is_(True))
        .order_by(model.DeviceGroup.group, model.User.label)
    )
    datalists = defaultdict(list)
    for dept, user_id, name in model.db.session.execute(statement).all():
        datalists[dept].append((user_id, user_datalist_entry(user_id, name)))
    return datalists


def member_datalists_by_group_for(
    device: model.Device, user: model.User
) -> Dict[str, Datalist]:
    users_departments = (
        select(model.Group.id.label("group_id"))
        .join(model.GroupMember, model.GroupMember.group == model.Group.id)
        .where(model.Group.department.is_(True))
        .where(model.Group.active.is_(True))
        .where(model.GroupMember.approved.is_not(None))
        .where(model.GroupMember.user == user.id)
        .subquery()
    )
    statement = (
        select(model.DeviceGroup.group, model.GroupMember.user, model.User.label)
        .join(
            users_departments, users_departments.c.group_id == model.DeviceGroup.group
        )
        .join(model.GroupMember, model.GroupMember.group == model.DeviceGroup.group)
        .join(model.User, model.User.id == model.GroupMember.user)
        .where(model.DeviceGroup.device == device.id)
        .where(model.GroupMember.approved.is_not(None))
        .order_by(model.DeviceGroup.group, model.User.label)
    )
    datalists = defaultdict(list)
    for dept, user_id, name in model.db.session.execute(statement).all():
        datalists[dept].append((user_id, user_datalist_entry(user_id, name)))
    return datalists


def all_group_colors() -> Dict[str, str]:
    return dict(_cached_group_colors())


@lru_cache(maxsize=1)
def _cached_group_colors() -> Tuple[Tuple[str, str], ...]:
    statement = select(model.Group.id, model.Group.color)
    return tuple(model.db.session.execute(statement).all())


def _clear_reference_data_cache() -> None:
    _cached_group_colors.cache_clear()


def _format_group_datalist_entry(group_id: str, label: str) -> Tuple[str, str]:
    if label != group_id:
        label = f"{label} ({group_id})"
    return group_id, label


def _default_scheduler_groups_statement():
    return select(
        model.Group.id.label("group_id"),
        model.Group.label.label("group_label"),
    ).where(model.Group.id.in_(("training", "maint")))


def all_groups_of_device(device: model.Device) -> Datalist:
    device_groups = (
        select(
            model.Group.id.label("group_id"),
            model.Group.label.label("group_label"),
        )
        .join(model.DeviceGroup, model.DeviceGroup.group == model.Group.id)
        .where(model.DeviceGroup.device == device.id)
        .where(model.Group.department.is_(True))
        .where(model.Group.active.is_(True))
    )
    group_rows = union(device_groups, _default_scheduler_groups_statement()).subquery()
    statement = select(group_rows.c.group_id, group_rows.c.group_label).order_by(
        group_rows.c.group_label, group_rows.c.group_id
    )
    return [
        _format_group_datalist_entry(group_id, label)
        for group_id, label in model.db.session.execute(statement).all()
    ]


def groups_of_device_for(device: model.Device, user: model.User) -> Datalist:
    users_departments = (
        select(
            model.Group.id.label("group_id"),
            model.Group.label.label("group_label"),
        )
        .join(model.GroupMember, model.GroupMember.group == model.Group.id)
        .where(model.Group.department.is_(True))
        .where(model.Group.active.is_(True))
        .where(model.GroupMember.approved.is_not(None))
        .where(model.GroupMember.user == user.id)
        .subquery()
    )
    visible_groups = (
        select(users_departments.c.group_id, users_departments.c.group_label)
        .join(
            model.DeviceGroup, model.DeviceGroup.group == users_departments.c.group_id
        )
        .where(model.DeviceGroup.device == device.id)
    )
    group_rows = union(visible_groups, _default_scheduler_groups_statement()).subquery()
    statement = select(group_rows.c.group_id, group_rows.c.group_label).order_by(
        group_rows.c.group_label, group_rows.c.group_id
    )
    return [
        _format_group_datalist_entry(group_id, label)
        for group_id, label in model.db.session.execute(statement).all()
    ]


def off_hours() -> Set[int]:
    return set(_OFF_HOURS)


def _used(entry: model.ScheduleEntry) -> bool:
    if entry.user is not None:
        return True
    for group_code in (entry.group, entry.orig_group):
        if group_code is not None and group_code not in ("", "DEV"):
            return True
    return False


def strike_used_off_hours(
    off_hour_set: Set[int], entries: List[model.ScheduleEntry]
) -> None:
    for entry in entries:
        if entry.hour in off_hour_set and _used(entry):
            off_hour_set.remove(entry.hour)
            if len(off_hour_set) == 0:
                break


def group_off_hours_into_runs(off_hour_set: Set[int]) -> List[List[int]]:
    sorted_hours = list(sorted(off_hour_set))
    sorted_hours += [99]

    acc, cur = [], []
    for hour, next_hour in zip(sorted_hours, sorted_hours[1:]):
        cur.append(hour)
        if next_hour == 99:
            cur.sort()
            acc.append(cur)
            break
        if next_hour - hour != 1:
            cur.sort()
            acc.append(cur)
            cur = []

    return acc


def convert_off_hour_runs_into_map(runs: List[List[int]]) -> Dict[int, List[int]]:
    out = {}
    for run in runs:
        out[run[0]] = run
    return out


def fmt_hours() -> Dict[int, str]:
    return dict(_FMT_HOURS)


def db_now() -> Tuple[datetime.date, int, int]:
    query = model.db.session.execute(
        text(
            """
        select
            (current_timestamp AT TIME ZONE 'America/New_York')::date,
            extract(
                hour from (current_timestamp AT TIME ZONE 'America/New_York')
            )::integer as hour,
            extract(
                minute from (current_timestamp AT TIME ZONE 'America/New_York')
            )::integer as minute
        """
        )
    )
    return query.first()


class JsonForm(FlaskForm):
    payload = fields.TextAreaField(validators=[validators.InputRequired()])


class CsrfOnlyForm(FlaskForm):
    pass
