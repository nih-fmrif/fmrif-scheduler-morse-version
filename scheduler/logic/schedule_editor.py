"""Scheduler edit and diff utilities."""

import datetime
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import DefaultDict, Dict, FrozenSet, List, NamedTuple, Optional, Set, Tuple

from flask_wtf import FlaskForm
from sqlalchemy.sql.functions import func
from wtforms import fields, validators

from scheduler import model

_FMT_HOURS = {
    0: "Mid.",
    12: "Noon",
}
_OFF_HOURS = frozenset({*range(0, 8), 22, 23})

for _i in range(1, 24):
    if _i == 12:
        continue
    _meridiem = "a" if _i < 12 else "p"
    _hour = _i if _i <= 12 else _i - 12
    _FMT_HOURS[_i] = f"{_hour}{_meridiem}m"

Datalist = List[Tuple[str, str]]


@dataclass(frozen=True)
class SchedulerStagedEntry:
    entry: model.ScheduleEntry
    server_ref: str


def schedule_for(
    device: model.Device, start: datetime.date, end: datetime.date
) -> List[model.ScheduleEntry]:
    entry_model = model.ScheduleEntry
    query = entry_model.query.filter(entry_model.device == device.id)
    query = query.filter(entry_model.date.between(start, end))
    query = query.order_by(entry_model.date, entry_model.hour)
    return query.all()


def schedule_for_hours(
    device: model.Device, start: datetime.date, end: datetime.date, hours: List[int]
) -> List[model.ScheduleEntry]:
    entry_model = model.ScheduleEntry
    query = entry_model.query.filter(entry_model.device == device.id)
    query = query.filter(entry_model.date.between(start, end))
    query = query.filter(entry_model.hour.in_(hours))
    query = query.order_by(entry_model.hour, entry_model.date)
    return query.all()


def schedule_exists_for(
    device: model.Device, start: datetime.date, end: datetime.date
) -> bool:
    entry_model = model.ScheduleEntry
    query = model.db.session.query(entry_model.id)
    query = query.filter(entry_model.device == device.id)
    query = query.filter(entry_model.date.between(start, end))
    return query.first() is not None


def schedule_used_hours_for(
    device: model.Device, start: datetime.date, end: datetime.date
) -> Set[int]:
    entry_model = model.ScheduleEntry
    query = model.db.session.query(entry_model.hour).filter(
        entry_model.device == device.id
    )
    query = query.filter(entry_model.date.between(start, end)).distinct()
    return set(hour for (hour,) in query.all())


def group_schedule_entries(
    entries: List[model.ScheduleEntry],
) -> Tuple[List[str], List[List[model.ScheduleEntry]]]:
    days = set()
    header = []
    grouped_entries: List[List[model.ScheduleEntry]] = []
    for _ in range(24):
        grouped_entries.append([])
    for entry in entries:
        if entry.date not in days:
            days.add(entry.date)
            header.append(fmt_date(entry.date, with_day=True))
        grouped_entries[entry.hour].append(entry)
    return header, grouped_entries


def group_template_entries(
    entries: List[model.TemplateEntry],
) -> List[List[model.TemplateEntry]]:
    grouped_entries: List[List[model.TemplateEntry]] = []
    for _ in range(24):
        grouped_entries.append([])
    for entry in entries:
        grouped_entries[entry.hour].append(entry)
    return grouped_entries


def device_schedule_extreme_dates(
    device: model.Device,
) -> Tuple[Optional[datetime.date], Optional[datetime.date]]:
    """Return the first and last scheduled day for a device."""
    entry_model = model.ScheduleEntry
    return (
        model.db.session.query(func.min(entry_model.date), func.max(entry_model.date))
        .filter(entry_model.device == device.id)
        .first()
    )


def next_schedule_day(
    device: model.Device, from_date: datetime.date, direction: int
) -> Optional[datetime.date]:
    """Find the nearest scheduled day before or after ``from_date`` for a device."""
    entry_model = model.ScheduleEntry
    if direction == 1:
        query = model.db.session.query(func.min(entry_model.date)).filter(
            entry_model.device == device.id,
            entry_model.date > from_date,
        )
    else:
        query = model.db.session.query(func.max(entry_model.date)).filter(
            entry_model.device == device.id,
            entry_model.date < from_date,
        )

    return query.scalar()


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
    """Parse a YYYY-MM-DD date string, returning None on failure."""
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_days(days: str) -> Optional[int]:
    """Parse a reasonable number of days (1-31), returning None on failure."""
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
    schedule_entry_model = model.ScheduleEntry
    entry = schedule_entry_model.query.filter(
        schedule_entry_model.id == entry_id
    ).first()
    if entry is None:
        return None
    return model.get(model.Device, entry.device)


def get_sched_log_entry(entry_id: int):
    log_entry = model.get(model.SchedLogEntry, entry_id)

    if log_entry is None:
        return None

    return log_entry.entries


class SupportRequestDatalists(NamedTuple):
    tech: Datalist
    medical: Datalist
    training: Datalist


def support_request_datalists(device: model.Device) -> SupportRequestDatalists:
    query = model.execute(
        """
            select r.researchercode, r.name, ud.tech, ud.medical, ud.training
            from userdevice ud
            inner join tlkpresearcher r using(researchercode)
            where r.active
            and ud.scannercode=:device
            and (ud.tech or ud.medical or ud.training)
            order by 2
        """,
        {
            "device": device.id,
        },
    )

    tech, med, train = [], [], []
    for user_id, name, is_tech, is_med, is_train in query.fetchall():
        pair = (user_id, user_datalist_entry(user_id, name))
        if is_tech:
            tech.append(pair)
        if is_med:
            med.append(pair)
        if is_train:
            train.append(pair)

    return SupportRequestDatalists(tech, med, train)


def all_member_datalists_by_group(device: model.Device) -> Dict[str, Datalist]:
    """For each department of device get a datalist of its members."""
    query = model.execute(
        """
            select dg.deptcode, gm.researchercode, r.name
            from devicegroup dg
            inner join tlkpdept dept on dept.deptcode = dg.deptcode
            inner join groupmembers gm on gm.deptcode = dg.deptcode
            inner join tlkpresearcher r on gm.researchercode = r.researchercode
            where dg.scannercode = :device
            and gm.approved is not null
            and dept.department and dept.iscurrent
            order by 1, 3
        """,
        {
            "device": device.id,
        },
    )
    datalists = defaultdict(list)
    for dept, user_id, name in query.fetchall():
        pair = (user_id, user_datalist_entry(user_id, name))
        datalists[dept].append(pair)
    return datalists


def member_datalists_by_group_for(
    device: model.Device, user: model.User
) -> Dict[str, Datalist]:
    """For each device group a user belongs to, get a member datalist."""
    query = model.execute(
        """
            with users_departments as (
                    select d.deptcode
                    from tlkpdept d
                    inner join groupmembers gm using(deptcode)
                    where d.department and d.iscurrent
                    and gm.approved is not null
                    and gm.researchercode = :user
                )
            select dg.deptcode, gm.researchercode, r.name
            from devicegroup dg
            inner join users_departments dept on dept.deptcode = dg.deptcode
            inner join groupmembers gm on gm.deptcode = dg.deptcode
            inner join tlkpresearcher r on gm.researchercode = r.researchercode
            where dg.scannercode = :device
            and gm.approved is not null
            order by 1, 3
        """,
        {
            "device": device.id,
            "user": user.id,
        },
    )
    datalists = defaultdict(list)
    for dept, user_id, name in query.fetchall():
        pair = (user_id, user_datalist_entry(user_id, name))
        datalists[dept].append(pair)
    return datalists


def all_group_colors() -> Dict[str, str]:
    # Old schedule rows may reference historical groups, so include every group color.
    return dict(_cached_group_colors())


@lru_cache(maxsize=1)
def _cached_group_colors() -> Tuple[Tuple[str, str], ...]:
    query = model.execute(
        """
            select d.deptcode, d.color
            from tlkpdept d
        """,
    )
    return tuple((key, value) for key, value in query.fetchall())


def _clear_reference_data_cache() -> None:
    _cached_group_colors.cache_clear()


def all_groups_of_device(device: model.Device) -> Datalist:
    query = model.execute(
        """
            select g.deptcode, g.dept_short
            from devicegroup dg
            inner join tlkpdept g using(deptcode)
            where dg.scannercode = :device
            and g.department and g.iscurrent
            union
            select deptcode, dept_short
            from tlkpdept
            where deptcode in ('training', 'maint')
        """,
        {
            "device": device.id,
        },
    )
    out = []
    for group_id, name in query.fetchall():
        if name != group_id:
            name = f"{name} ({group_id})"
        out.append((group_id, name))
    return out


def groups_of_device_for(device: model.Device, user: model.User) -> Datalist:
    query = model.execute(
        """
            with users_departments as (
                select d.deptcode, d.dept_short
                from tlkpdept d
                inner join groupmembers gm using(deptcode)
                where d.department and d.iscurrent
                and gm.approved is not null
                and gm.researchercode = :user
            )
            select g.deptcode, g.dept_short
            from devicegroup dg
            inner join users_departments g using(deptcode)
            where dg.scannercode = :device
            union
            select deptcode, dept_short
            from tlkpdept
            where deptcode in ('training', 'maint')
        """,
        {
            "device": device.id,
            "user": user.id,
        },
    )
    out = []
    for group_id, name in query.fetchall():
        if name != group_id:
            name = f"{name} ({group_id})"
        out.append((group_id, name))
    return out


def off_hours() -> Set[int]:
    """Return set of standard off-hours."""
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
    """Remove any off-hours that are used by any entry."""
    for entry in entries:
        if entry.hour in off_hour_set and _used(entry):
            off_hour_set.remove(entry.hour)
            if len(off_hour_set) == 0:
                break


def group_off_hours_into_runs(off_hour_set: Set[int]) -> List[List[int]]:
    sorted_hours = list(sorted(off_hour_set))
    sorted_hours += [99]  # sentinel

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
    """Get current day, hour, and minute from the DB transaction."""
    query = model.execute(
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
    return query.first()


class JsonForm(FlaskForm):
    """Form used for JS JSON payload submissions."""

    payload = fields.TextAreaField(validators=[validators.InputRequired()])


class CsrfOnlyForm(FlaskForm):
    """Use when a route needs CSRF validation without additional fields."""

    pass


def verify_and_prep_template_diffs(
    diffs, entries, institutes, groups, members_of_groups
):
    ids = frozenset(int(diff["id"]) for diff in diffs)
    referenced = {entry.id: entry for entry in entries if entry.id in ids}

    inst = frozenset(entry_id for (entry_id, _) in institutes)
    available_groups = frozenset(entry_id for (entry_id, _) in groups)
    members = {
        "": frozenset(),
        "maint": frozenset(),
        "training": frozenset(),
    }
    for group_id, values in members_of_groups.items():
        members[group_id] = frozenset(entry_id for (entry_id, _) in values)

    errors = defaultdict(list)
    staged = []

    def check(entry_id, diff, key, entry_val, valid_set):
        if entry_val is None:
            entry_val = ""
        if key not in diff:
            return entry_val, True
        old, new = diff[key]
        failed = False
        if entry_val != "" and entry_val != old:
            errors[entry_id].append(
                {
                    "type": "overwrote",
                    "key": key,
                    "expected": old,
                    "got": entry_val,
                }
            )
            failed = True
        ret = entry_val
        if new:
            ret = new
            if new not in valid_set:
                errors[entry_id].append(
                    {
                        "type": "removed",
                        "key": key,
                        "value": new,
                    }
                )
                failed = True
        return ret, not failed

    for diff in diffs:
        entry_id = int(diff["id"])
        entry = referenced[entry_id]
        check(entry_id, diff, "institute", entry.inst, inst)
        group, ok = check(entry_id, diff, "group", entry.group, available_groups)
        if ok:
            check(entry_id, diff, "member", entry.user, members[group])

        if entry_id not in errors:
            if "institute" in diff:
                entry.inst = diff["institute"][1] or None
            if "group" in diff:
                entry.group = diff["group"][1] or None
            if "member" in diff:
                entry.user = diff["member"][1] or None
            staged.append(entry)

    if len(errors) > 0:
        return [], errors
    return staged, None


def is_old(
    entry_date: datetime.date,
    entry_hour: int,
    cur_date: datetime.date,
    cur_hour: int,
    cur_minute: int,
    shift: bool = True,
) -> bool:
    current_dt = datetime.datetime(
        cur_date.year, cur_date.month, cur_date.day, cur_hour, cur_minute
    )
    entry_dt = datetime.datetime(
        entry_date.year, entry_date.month, entry_date.day, entry_hour, 0
    )
    if shift:
        entry_dt -= datetime.timedelta(minutes=15)
    return entry_dt < current_dt


def null2epsilon(value: Optional[str]) -> str:
    if value is None:
        return ""
    return value


def verify_scheduler_diffs(
    diffs,
    entries: List[model.ScheduleEntry],
    perms,
    support: SupportRequestDatalists,
    cur_date: datetime.date,
    cur_hour: int,
    cur_minute: int,
    groups: Datalist,
    members_of_groups: Dict[str, Datalist],
    user: model.User,
):
    ids = frozenset(int(diff["id"]) for diff in diffs)
    referenced = {entry.id: entry for entry in entries if entry.id in ids}
    when = {}
    xs = []
    for diff in diffs:
        entry_id = int(diff["id"])
        entry = referenced[entry_id]
        xs.append((entry_id, diff, entry))
        past = is_old(
            entry.date, entry.hour, cur_date, cur_hour, cur_minute, shift=False
        )
        when[entry_id] = (past, entry.date, entry.hour)

    errors: DefaultDict[int, List[Dict[str, str]]] = defaultdict(list)

    def fail(entry_id: int, msg: Dict[str, str]) -> None:
        errors[entry_id].append(msg)

    def fail_removed(entry_id, key, value):
        fail(entry_id, {"type": "removed", "key": key, "value": value})

    def fail_overwrote(entry_id, key, expected, got):
        fail(
            entry_id,
            {
                "type": "overwrote",
                "key": key,
                "expected": expected,
                "got": got,
            },
        )

    def fail_user_removed(entry_id, key, value):
        fail(entry_id, {"type": "user-removed", "key": key, "value": value})

    def compact():
        if len(xs) != len(referenced):
            return [
                (entry_id, diff, entry)
                for entry_id, diff, entry in xs
                if entry_id in referenced
            ]
        return xs

    if not perms.edit_any:
        for entry_id, _, entry in xs:
            if is_old(entry.date, entry.hour, cur_date, cur_hour, cur_minute):
                fail(entry_id, {"type": "expired"})
                del referenced[entry_id]
        if len(referenced) == 0:
            return [], [], {}, errors

        xs = compact()

    valid_groups = frozenset(group_id for (group_id, _) in groups)

    members: Dict[str, FrozenSet[str]] = {
        "": frozenset(),
        "maint": frozenset(),
        "training": frozenset(user_id for (user_id, _) in support.training),
    }
    for group_id, values in members_of_groups.items():
        members[group_id] = frozenset(user_id for (user_id, _) in values)

    for entry_id, diff, entry in xs:
        group = null2epsilon(entry.group)

        if "group" not in diff:
            if group != "" and group not in valid_groups:
                fail_removed(entry_id, "group", group)
                del referenced[entry_id]
            continue

        old, new = diff["group"]

        if group != "" and group != old:
            fail_overwrote(entry_id, "group", group, old)
            del referenced[entry_id]
            continue

        if new != "" and new not in valid_groups:
            fail_removed(entry_id, "group", new)
            del referenced[entry_id]
            continue

        if not perms.edit_any:
            if old != "" and user.id not in members[old]:
                fail_user_removed(entry_id, "group", old)
                del referenced[entry_id]

            if new != "" and user.id not in members[new]:
                fail_user_removed(entry_id, "group", new)
                del referenced[entry_id]

    xs = compact()

    for entry_id, diff, entry in xs:
        if "member" not in diff:
            continue

        old, new = diff["member"]

        member = null2epsilon(entry.user)
        if member != "" and old != member:
            fail_overwrote(entry_id, "member", member, old)

        if new != "":
            group = null2epsilon(entry.group)
            if "group" in diff:
                _, group = diff["group"]

            if new not in members[group]:
                fail_removed(entry_id, "member", new)

    srs: List[model.SupportRequest] = []

    def get_sr(entry, kind):
        for sr in entry.requests:
            if sr.supportkind == kind:
                return sr, False

        sr = model.SupportRequest()
        sr.supportkind = kind
        sr.filed_by = user.id
        sr.modified_by = user.id
        entry.requests.append(sr)
        return sr, True

    support_human_name = {
        1: "medical",
        2: "training",
        3: "technologist",
    }

    support_staff = {
        1: frozenset(user_id for (user_id, _) in support.medical),
        2: frozenset(user_id for (user_id, _) in support.training),
        3: frozenset(user_id for (user_id, _) in support.tech),
    }

    def record_sr(entry_id, diff, entry, key, kind):
        if key not in diff:
            return
        srs.append(
            (
                entry_id,
                support_human_name[kind],
                diff[key],
                *get_sr(entry, kind),
                user.id in support_staff[kind] or perms.edit_any,
            )
        )

    for entry_id, diff, entry in xs:
        record_sr(entry_id, diff, entry, "med", 1)
        record_sr(entry_id, diff, entry, "train", 2)
        record_sr(entry_id, diff, entry, "tech", 3)

    def returns():
        if len(errors) > 0:
            return [], [], {}, errors
        return xs, srs, when, None

    if len(srs) == 0:
        return returns()

    for entry_id, kind, diff, sr, is_new, _ in srs:
        if not is_new and "handler" in diff:
            old, _ = diff["handler"]
            handler = null2epsilon(sr.fulfilled_by)
            if handler != "" and handler != old:
                fail_overwrote(entry_id, f"{kind} handler", handler, old)

        if "requested" in diff and not diff["requested"]:
            continue

        if "handler" in diff:
            _, new = diff["handler"]
            if new != "" and new not in support_staff[sr.supportkind]:
                fail_removed(entry_id, f"{kind} handler", new)

    return returns()


def apply_scheduler_diffs(user: model.User, xs):
    stage = []
    for _, diff, entry in xs:
        entry.modified_by = user.id
        if "group" in diff:
            entry.group = diff["group"][1] or None
        if "member" in diff:
            entry.user = diff["member"][1] or None
        stage.append(
            SchedulerStagedEntry(
                entry=entry,
                server_ref=str(diff.get("_server_ref") or entry.id),
            )
        )
    return stage


def apply_scheduler_sr_diffs(user: model.User, srs):
    notes = []
    for entry_id, kind, diff, sr, is_new, staff_request in srs:
        note = {"id": entry_id, "kind": kind}
        sr.modified_by = user.id

        note["state"] = "new" if is_new else "updated"

        if "subkind" in diff:
            sr.note = diff["subkind"][1]
            note["subkind"] = diff["subkind"]

        canceled = False
        decision = sr.approved or False
        if "requested" in diff:
            if diff["requested"]:
                sr.approved = None
            else:
                canceled = True
                sr.fulfilled_by = None
                note["state"] = "retracted"
                if staff_request:
                    sr.approved = False
                    note["state"] = "denied"
                    if decision:
                        note["state"] = "canceled"

        if "handler" in diff and not canceled:
            old, new = diff["handler"]
            sr.fulfilled_by = new or None

            if new != "":
                note["handler"] = new

            if old == "" and new != "":
                sr.approved = True
                note["state"] = "approved"
            elif old != "" and new == "":
                sr.approved = None
                note["state"] = "unassigned"
            else:
                note["state"] = "reassigned"

        notes.append(note)
    return notes


__all__ = [
    "JsonForm",
    "CsrfOnlyForm",
    "SupportRequestDatalists",
    "schedule_for",
    "schedule_for_hours",
    "schedule_exists_for",
    "schedule_used_hours_for",
    "group_schedule_entries",
    "group_template_entries",
    "device_schedule_extreme_dates",
    "next_schedule_day",
    "date_or_today",
    "fmt_date",
    "parse_date",
    "parse_days",
    "end_date",
    "user_datalist_entry",
    "get_device_from_schedid",
    "get_sched_log_entry",
    "support_request_datalists",
    "all_member_datalists_by_group",
    "member_datalists_by_group_for",
    "all_group_colors",
    "all_groups_of_device",
    "groups_of_device_for",
    "off_hours",
    "strike_used_off_hours",
    "group_off_hours_into_runs",
    "convert_off_hour_runs_into_map",
    "fmt_hours",
    "db_now",
    "verify_and_prep_template_diffs",
    "is_old",
    "null2epsilon",
    "verify_scheduler_diffs",
    "apply_scheduler_diffs",
    "apply_scheduler_sr_diffs",
]
