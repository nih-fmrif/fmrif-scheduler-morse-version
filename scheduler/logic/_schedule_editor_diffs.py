from __future__ import annotations

import datetime
from collections import defaultdict
from typing import DefaultDict, Dict, FrozenSet, List, Optional, Tuple

from scheduler import model

from ._schedule_editor_shared import (
    Datalist,
    SchedulerStagedEntry,
    SupportRequestDatalists,
)

_SUPPORT_PERMISSION_ATTRS = {
    1: "medical",
    2: "training",
    3: "tech",
}
_SUPPORT_DIFF_KEYS = frozenset({"med", "train", "tech"})
_SUPPORT_BOOKING_KEYS = frozenset({"requested", "subkind"})
_SUPPORT_HUMAN_NAMES = {
    1: "medical",
    2: "training",
    3: "technologist",
}


def _support_diff_requires_booking_edit(diff: object) -> bool:
    if not isinstance(diff, dict):
        return False
    return any(key in diff for key in _SUPPORT_BOOKING_KEYS)


def _diff_requires_booking_edit(diff: dict) -> bool:
    if "group" in diff or "member" in diff:
        return True
    return any(
        _support_diff_requires_booking_edit(diff.get(key)) for key in _SUPPORT_DIFF_KEYS
    )


def _support_request_is_active(sr: Optional[model.SupportRequest]) -> bool:
    return sr is not None and sr.approved is not False


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
            normalized_group = "" if group in (None, "", "(none)") else group
            check(entry_id, diff, "member", entry.user, members[normalized_group])

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


def _scheduler_diff_rows(
    diffs,
    entries: List[model.ScheduleEntry],
    *,
    cur_date: datetime.date,
    cur_hour: int,
    cur_minute: int,
):
    ids = frozenset(int(diff["id"]) for diff in diffs)
    referenced = {entry.id: entry for entry in entries if entry.id in ids}
    when = {}
    rows = []
    for diff in diffs:
        entry_id = int(diff["id"])
        entry = referenced[entry_id]
        rows.append((entry_id, diff, entry))
        when[entry_id] = (
            is_old(entry.date, entry.hour, cur_date, cur_hour, cur_minute, shift=False),
            entry.date,
            entry.hour,
        )
    return referenced, rows, when


def _scheduler_compact_rows(rows, referenced):
    if len(rows) != len(referenced):
        return [
            (entry_id, diff, entry)
            for entry_id, diff, entry in rows
            if entry_id in referenced
        ]
    return rows


def _scheduler_fail(
    errors: DefaultDict[int, List[Dict[str, str]]], entry_id: int, msg: Dict[str, str]
) -> None:
    errors[entry_id].append(msg)


def _scheduler_fail_removed(
    errors: DefaultDict[int, List[Dict[str, str]]], entry_id: int, key: str, value: str
) -> None:
    _scheduler_fail(errors, entry_id, {"type": "removed", "key": key, "value": value})


def _scheduler_fail_overwrote(
    errors: DefaultDict[int, List[Dict[str, str]]],
    entry_id: int,
    key: str,
    expected: str,
    got: str,
) -> None:
    _scheduler_fail(
        errors,
        entry_id,
        {
            "type": "overwrote",
            "key": key,
            "expected": expected,
            "got": got,
        },
    )


def _scheduler_fail_user_removed(
    errors: DefaultDict[int, List[Dict[str, str]]], entry_id: int, key: str, value: str
) -> None:
    _scheduler_fail(
        errors,
        entry_id,
        {"type": "user-removed", "key": key, "value": value},
    )


def _scheduler_fail_permission(
    errors: DefaultDict[int, List[Dict[str, str]]],
    entry_id: int,
    message: str,
    source: str = "permission",
) -> None:
    _scheduler_fail(errors, entry_id, {"source": source, "message": message})


def _build_scheduler_members(
    support: SupportRequestDatalists,
    members_of_groups: Dict[str, Datalist],
) -> Dict[str, FrozenSet[str]]:
    members: Dict[str, FrozenSet[str]] = {
        "": frozenset(),
        "maint": frozenset(),
        "training": frozenset(user_id for (user_id, _) in support.training),
    }
    for group_id, values in members_of_groups.items():
        members[group_id] = frozenset(user_id for (user_id, _) in values)
    return members


def _filter_uneditable_scheduler_rows(
    rows,
    referenced,
    errors: DefaultDict[int, List[Dict[str, str]]],
    *,
    perms,
    cur_date: datetime.date,
    cur_hour: int,
    cur_minute: int,
):
    if not perms.edit_any:
        for entry_id, _, entry in rows:
            if is_old(entry.date, entry.hour, cur_date, cur_hour, cur_minute):
                _scheduler_fail(errors, entry_id, {"type": "expired"})
                del referenced[entry_id]
        if len(referenced) == 0:
            return []
        rows = _scheduler_compact_rows(rows, referenced)

    if not perms.edit:
        for entry_id, diff, _ in rows:
            if _diff_requires_booking_edit(diff):
                _scheduler_fail_permission(
                    errors,
                    entry_id,
                    "this change requires booking edit access",
                )
                del referenced[entry_id]
        if len(referenced) == 0:
            return []
        rows = _scheduler_compact_rows(rows, referenced)

    return rows


def _validate_group_diffs(
    rows,
    referenced,
    errors: DefaultDict[int, List[Dict[str, str]]],
    *,
    perms,
    user: model.User,
    groups: Datalist,
    members: Dict[str, FrozenSet[str]],
):
    valid_groups = frozenset(group_id for (group_id, _) in groups)
    for entry_id, diff, entry in rows:
        if not perms.edit and not _diff_requires_booking_edit(diff):
            continue
        group = null2epsilon(entry.group)

        if "group" not in diff:
            if group != "" and group not in valid_groups:
                _scheduler_fail_removed(errors, entry_id, "group", group)
                del referenced[entry_id]
            continue

        old, new = diff["group"]
        if group != "" and group != old:
            _scheduler_fail_overwrote(errors, entry_id, "group", group, old)
            del referenced[entry_id]
            continue
        if new != "" and new not in valid_groups:
            _scheduler_fail_removed(errors, entry_id, "group", new)
            del referenced[entry_id]
            continue

        if not perms.edit_any:
            if old != "" and user.id not in members[old]:
                _scheduler_fail_user_removed(errors, entry_id, "group", old)
                del referenced[entry_id]
            if new != "" and user.id not in members[new]:
                _scheduler_fail_user_removed(errors, entry_id, "group", new)
                del referenced[entry_id]

    return _scheduler_compact_rows(rows, referenced)


def _validate_member_diffs(
    rows,
    errors: DefaultDict[int, List[Dict[str, str]]],
    *,
    perms,
    members: Dict[str, FrozenSet[str]],
):
    for entry_id, diff, entry in rows:
        if not perms.edit and not _diff_requires_booking_edit(diff):
            continue
        if "member" not in diff:
            continue

        old, new = diff["member"]
        member = null2epsilon(entry.user)
        if member != "" and old != member:
            _scheduler_fail_overwrote(errors, entry_id, "member", member, old)

        if new != "":
            group = null2epsilon(entry.group)
            if "group" in diff:
                _, group = diff["group"]
            if new not in members[group]:
                _scheduler_fail_removed(errors, entry_id, "member", new)


def _get_support_request(entry, kind, user: model.User):
    for sr in entry.requests:
        if sr.supportkind == kind:
            return sr, False

    sr = model.SupportRequest()
    sr.supportkind = kind
    sr.filed_by = user.id
    sr.modified_by = user.id
    entry.requests.append(sr)
    return sr, True


def _build_support_staff(support: SupportRequestDatalists) -> Dict[int, FrozenSet[str]]:
    return {
        1: frozenset(user_id for (user_id, _) in support.medical),
        2: frozenset(user_id for (user_id, _) in support.training),
        3: frozenset(user_id for (user_id, _) in support.tech),
    }


def _collect_support_request_diffs(rows, user: model.User, support_staff, perms):
    srs: List[Tuple[int, str, dict, model.SupportRequest, bool, bool]] = []

    for entry_id, diff, entry in rows:
        for key, kind in (("med", 1), ("train", 2), ("tech", 3)):
            if key not in diff:
                continue
            sr, is_new = _get_support_request(entry, kind, user)
            srs.append(
                (
                    entry_id,
                    _SUPPORT_HUMAN_NAMES[kind],
                    diff[key],
                    sr,
                    is_new,
                    user.id in support_staff[kind] or perms.edit_any,
                )
            )
    return srs


def _validate_support_request_diffs(
    srs,
    errors: DefaultDict[int, List[Dict[str, str]]],
    *,
    perms,
    support_staff,
):
    for entry_id, kind, diff, sr, is_new, _staff_request in srs:
        permission_attr = _SUPPORT_PERMISSION_ATTRS[sr.supportkind]
        request_active = _support_request_is_active(None if is_new else sr)
        request_will_be_active = diff.get("requested", request_active)

        if _support_diff_requires_booking_edit(diff) and not perms.edit:
            _scheduler_fail_permission(
                errors,
                entry_id,
                "this change requires booking edit access",
                kind,
            )
            continue

        if "requested" in diff and not diff["requested"]:
            continue

        if "handler" in diff and not getattr(perms, permission_attr):
            _scheduler_fail_permission(
                errors,
                entry_id,
                f"{kind} handler changes require {kind} support access",
                kind,
            )
            continue

        if not is_new and "handler" in diff:
            old, _ = diff["handler"]
            handler = null2epsilon(sr.fulfilled_by)
            if handler != "" and handler != old:
                _scheduler_fail_overwrote(
                    errors,
                    entry_id,
                    f"{kind} handler",
                    handler,
                    old,
                )

        if "handler" in diff:
            if not request_will_be_active:
                _scheduler_fail_permission(
                    errors,
                    entry_id,
                    "no active request to fulfill",
                    kind,
                )
                continue
            _, new = diff["handler"]
            if new != "" and new not in support_staff[sr.supportkind]:
                _scheduler_fail_removed(errors, entry_id, f"{kind} handler", new)


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
    referenced, rows, when = _scheduler_diff_rows(
        diffs,
        entries,
        cur_date=cur_date,
        cur_hour=cur_hour,
        cur_minute=cur_minute,
    )
    errors: DefaultDict[int, List[Dict[str, str]]] = defaultdict(list)

    rows = _filter_uneditable_scheduler_rows(
        rows,
        referenced,
        errors,
        perms=perms,
        cur_date=cur_date,
        cur_hour=cur_hour,
        cur_minute=cur_minute,
    )
    if len(referenced) == 0:
        return [], [], {}, errors

    members = _build_scheduler_members(support, members_of_groups)
    rows = _validate_group_diffs(
        rows,
        referenced,
        errors,
        perms=perms,
        user=user,
        groups=groups,
        members=members,
    )
    _validate_member_diffs(rows, errors, perms=perms, members=members)

    support_staff = _build_support_staff(support)
    srs = _collect_support_request_diffs(rows, user, support_staff, perms)
    if len(srs) == 0:
        if len(errors) > 0:
            return [], [], {}, errors
        return rows, [], when, None

    _validate_support_request_diffs(
        srs, errors, perms=perms, support_staff=support_staff
    )
    if len(errors) > 0:
        return [], [], {}, errors
    return rows, srs, when, None


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
