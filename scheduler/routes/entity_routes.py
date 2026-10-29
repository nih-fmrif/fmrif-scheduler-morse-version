from __future__ import annotations

import datetime
import re
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from flask import abort, current_app, g, jsonify, request, url_for
from flask.helpers import flash
from flask.templating import render_template
from sqlalchemy.exc import SQLAlchemyError

from scheduler import logic, model
from scheduler.scheduler_save_error_attribution import (
    build_scheduler_diff_context,
    select_scheduler_error_client_ids,
)
from scheduler.scheduler_save_error_policy import explain_scheduler_save_error

BreadcrumbLinks = Dict[str, List[Tuple[str, str]]]
SubpageLinks = Dict[str, Dict[str, Union[str, List[Tuple[str, str]]]]]

_my_url_fn: Optional[Callable[[], str]] = None
_to_fn: Optional[Callable[..., Any]] = None
_breadcrumb_fn: Optional[Callable[..., BreadcrumbLinks]] = None
_subpage_nav_fn: Optional[
    Callable[[str, List[Tuple[bool, str, str]]], SubpageLinks]
] = None
_SYNTHETIC_SLOT_ID = re.compile(r"^new-(\d{4}-\d{2}-\d{2})-(\d{1,2})$")
DB_CLOCK_WARNING = "Database time unavailable. Unable to refresh ET date right now."


class SlotSaveNormalizationError(Exception):
    def __init__(self, slot_id: str, source: str, code: str, message: str):
        super().__init__(message)
        self.slot_id = slot_id
        self.source = source
        self.code = code
        self.message = message


def _db_clock_date() -> Tuple[Optional[datetime.date], Optional[str]]:
    try:
        return logic.db_now()[0], None
    except SQLAlchemyError:
        current_app.logger.exception(
            "unable to resolve DB ET clock for scheduler date defaults"
        )
        return None, DB_CLOCK_WARNING


def _require_helper(
    helper: Optional[Callable[..., Any]], name: str
) -> Callable[..., Any]:
    if helper is None:
        raise RuntimeError(f"Route helper not configured: {name}")
    return helper


def my_url() -> str:
    return _require_helper(_my_url_fn, "my_url")()


def to(page: str, **kwargs: Any) -> Any:
    return _require_helper(_to_fn, "to")(page, **kwargs)


def breadcrumb(*routes: Union[str, Tuple[str, str]]) -> BreadcrumbLinks:
    return _require_helper(_breadcrumb_fn, "breadcrumb")(*routes)


def subpage_nav(title: str, links: List[Tuple[bool, str, str]]) -> SubpageLinks:
    return _require_helper(_subpage_nav_fn, "subpage_nav")(title, links)


# shared subpage nav for all group pages
def group_subpage_nav(group: model.Group, su: logic.Group_leader_kind) -> SubpageLinks:
    _ = su
    return subpage_nav(
        "group",
        [
            # view has further protections, but if you can see any of them you can see it
            (True, f"view [{group.label}]", url_for("group", the_group=group.id)),
        ],
    )


def group_breadcrumb(group: model.Group) -> BreadcrumbLinks:
    return breadcrumb((group.label, url_for("group", the_group=group.id)))


def group(the_group):
    group = logic.get_group(the_group)
    if group is None:
        abort(404)

    su = logic.get_group_leader_kind(g.user, group)

    # inactive groups cannot be viewed from this page.
    if not group.active:
        abort(403)

    members = logic.get_members_of_group(group)

    # must be admin, dev_pi, or member
    if not (len(su) > 0 or any(m == g.user.id for (m, _, _) in members)):
        abort(403)

    return {
        "group": group,
        "members": members,
        "su": su,
        **group_subpage_nav(group, su),
        **group_breadcrumb(group),
    }


def device_breadcrumb(device: model.Device) -> BreadcrumbLinks:
    return breadcrumb((device.label, url_for("device", the_device=device.id)))


def schedule_window_from_request(device: Optional[model.Device] = None) -> tuple:
    # get the date, defaulting to DB clock
    date = None
    the_date = request.args.get("start")
    if the_date is not None:
        date = logic.parse_date(the_date)
        if date is None:
            abort(400, f"invalid start: {the_date} (must be YYYY-MM-DD date)")
    clock_warning = None
    if date is None:
        date, clock_warning = _db_clock_date()
    if date is None:
        abort(503, DB_CLOCK_WARNING)

    # get the number of days to show, defaulting to 7
    days = 7
    the_days = request.args.get("days")
    if the_days is not None:
        days = logic.parse_days(the_days)
        if days is None:
            abort(400, f"invalid days: {the_days} (must be in 1-31)")

    # day windows are inclusive of the start date, so subtract one day here.
    end_date = logic.end_date(date, days - 1)

    return date, days, end_date, clock_warning


def _slot_stub(day, hour: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"new-{logic.fmt_date(day)}-{hour:02d}",
        hour=hour,
        date=day,
        group="",
        user="",
        requests=[],
        error=False,
        template=None,
        used=None,
        errors=[],
    )


def _db_weekday_for(date_value) -> int:
    # DB schema expects 0=Sunday,1=Monday,...,6=Saturday
    return int(date_value.isoweekday()) % 7


def _slot_error_row(
    source: str, code: str, message: str, blocking: bool = True
) -> Dict[str, Union[str, bool]]:
    return {
        "source": source,
        "code": code,
        "message": message,
        "blocking": blocking,
        "origin": "server",
    }


def _log_scheduler_save_database_error(
    err: SQLAlchemyError, *, phase: str
) -> Dict[str, Union[str, bool]]:
    decision = explain_scheduler_save_error(err)
    logger = current_app.logger if current_app else None
    if logger:
        if decision.notify_admin:
            logger.exception(
                "Scheduler save %s hit an unmapped database error policy path",
                phase,
            )
        else:
            logger.warning(
                "Scheduler save %s rejected by approved database policy "
                "(code=%s, source=%s)",
                phase,
                decision.code,
                decision.source,
            )
    return _slot_error_row(
        decision.source,
        decision.code,
        decision.message,
        blocking=True,
    )


def _map_server_errors_to_client_ids(errors, synthetic_map):
    mapped_errors = {}
    for entry_id, rows in errors.items():
        key = synthetic_map.get(str(entry_id), str(entry_id))
        mapped_errors[key] = rows
    return mapped_errors


def _build_error_map_for_client_ids(client_ids, row):
    mapped = {}
    for client_id in client_ids:
        key = str(client_id)
        mapped.setdefault(key, []).append(dict(row))
    if len(mapped) == 0:
        mapped["slot"] = [dict(row)]
    return mapped


def _normalize_schedule_diffs_for_save(diffs, entries, device, user):
    by_slot = {(entry.date, int(entry.hour)): entry for entry in entries}
    normalized = []
    server_to_client = {}
    diff_contexts = {}
    for raw in diffs:
        diff = dict(raw)
        raw_id = diff.get("id")
        client_id = str(raw_id)
        if isinstance(raw_id, str):
            match = _SYNTHETIC_SLOT_ID.fullmatch(raw_id.strip())
            if match is not None:
                slot_date = logic.parse_date(match.group(1))
                slot_hour = int(match.group(2))
                if diff.get("date") is not None:
                    parsed = logic.parse_date(str(diff.get("date")))
                    if parsed is not None:
                        slot_date = parsed
                if diff.get("hour") is not None:
                    try:
                        slot_hour = int(diff.get("hour"))
                    except (TypeError, ValueError):
                        raise SlotSaveNormalizationError(
                            raw_id,
                            "hour",
                            "invalid_hour",
                            f"invalid hour for synthetic slot id: {raw_id}",
                        )
                if slot_date is None or slot_hour < 0 or slot_hour > 23:
                    raise SlotSaveNormalizationError(
                        raw_id,
                        "slot",
                        "invalid_slot",
                        f"invalid synthetic slot id: {raw_id}",
                    )
                slot = (slot_date, slot_hour)
                entry = by_slot.get(slot)
                if entry is None:
                    entry = model.ScheduleEntry()
                    entry.device = device.id
                    entry.date = slot_date
                    entry.dow = _db_weekday_for(slot_date)
                    entry.hour = slot_hour
                    entry.group = None
                    entry.user = None
                    entry.orig_group = None
                    entry.orig_inst = None
                    entry.template = None
                    entry.used = None
                    entry.modified_by = user.id
                    model.db.session.add(entry)
                    try:
                        model.db.session.flush()
                    except SQLAlchemyError as err:
                        row = _log_scheduler_save_database_error(
                            err, phase="synthetic slot normalization"
                        )
                        raise SlotSaveNormalizationError(
                            raw_id,
                            str(row["source"]),
                            str(row["code"]),
                            str(row["message"]),
                        ) from err
                    entries.append(entry)
                    by_slot[slot] = entry
                diff["id"] = entry.id
                server_to_client[str(entry.id)] = raw_id
        server_ref = f"d{len(normalized)}"
        diff["_server_ref"] = server_ref
        diff_contexts[server_ref] = build_scheduler_diff_context(
            server_ref, client_id, diff
        )
        normalized.append(diff)
    return normalized, server_to_client, diff_contexts


def device_subpage_nav(device: model.Device, perms: logic.DevicePerms) -> SubpageLinks:
    def can(permission: bool) -> bool:
        return perms.admin or (permission and device.active)

    id = device.id
    return subpage_nav(
        f"device [{device.label}]",
        [
            (True, "schedule", url_for("device", the_device=id)),
            (can(perms.template), "templates", url_for("device_tmpl", the_device=id)),
        ],
    )


def device(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)

    if not (device.active or perms.admin):
        abort(403)

    date, days, end_date, clock_warning = schedule_window_from_request(device)

    min, max = logic.device_schedule_extreme_dates(device)

    fmt_start_date = logic.fmt_date(date)
    fmt_end_date = logic.fmt_date(end_date)
    fmt_min = ""
    fmt_max = ""
    if min is not None:
        fmt_min = logic.fmt_date(min)
        fmt_max = logic.fmt_date(max)

    # compute which hours to hide by default
    off_hours = logic.off_hours()
    used_hours = logic.schedule_used_hours_for(device, date, end_date)
    has_entries_for_range = len(used_hours) > 0
    off_hours.difference_update(used_hours)
    off_hour_runs = logic.group_off_hours_into_runs(off_hours)
    off_hour_map = logic.convert_off_hour_runs_into_map(off_hour_runs)

    no_entries = ""
    never_entries = ""
    if not has_entries_for_range:
        if min is None:
            never_entries = "this device has not yet had any entries scheduled on it"
        else:
            no_entries = f"no entries scheduled for {fmt_start_date}. All entries are between {fmt_min} and {fmt_max}"

    colors = logic.all_group_colors()

    # need to determine if user can edit this
    support = logic.SupportRequestDatalists([], [], [])
    members_of_groups = {}
    groups = []
    selection_groups = []
    device_groups = logic.all_groups_of_device(device)
    can_fulfill_support = perms.tech or perms.medical or perms.training

    # load any data user may need to edit
    if device.active and (perms.edit or can_fulfill_support):
        support = logic.support_request_datalists(device)

        if perms.edit:
            # load all relevant group-member datalists
            if perms.edit_any:
                members_of_groups = logic.all_member_datalists_by_group(device)
                groups = device_groups
            else:
                members_of_groups = logic.member_datalists_by_group_for(device, g.user)
                groups = logic.groups_of_device_for(device, g.user)
                selection_groups = [
                    pair for pair in groups if pair[0] not in ("training", "maint")
                ]

            if not selection_groups:
                selection_groups = groups

    perms_json = {  # the permissions the js needs
        "edit": perms.edit,
        "edit_any": perms.edit_any,
        "tech": perms.tech,
        "medical": perms.medical,
        "training": perms.training,
    }
    groups_json = [id for (id, _) in groups]
    device_groups_json = [id for (id, _) in device_groups]

    header_weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    header_months = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    top_row = [
        (
            f"{(date + timedelta(days=n)).year} "
            f"{header_weekdays[(date + timedelta(days=n)).weekday()]} "
            f"({header_months[(date + timedelta(days=n)).month - 1]}-{(date + timedelta(days=n)).day:02d})"
            if n == 0
            else f"{header_weekdays[(date + timedelta(days=n)).weekday()]} ({header_months[(date + timedelta(days=n)).month - 1]}-{(date + timedelta(days=n)).day:02d})"
        )
        for n in range(days)
    ]

    hours = logic.fmt_hours()
    cur_date = date
    cur_hour = -1
    cur_minute = 0
    try:
        cur_date, cur_hour, cur_minute = logic.db_now()
    except SQLAlchemyError:
        current_app.logger.exception(
            "unable to resolve DB ET clock for scheduler operations"
        )
        clock_warning = clock_warning or DB_CLOCK_WARNING

    form = logic.JsonForm()
    if request.method == "POST":
        if not (perms.edit or can_fulfill_support):
            # direct request or user lost edit access between fetching page and submitting form
            abort(403)
        if not form.validate():
            # client response must specify payload
            abort(500)

        data = form.payload.data
        diffs = data["diffs"]
        send_notifications = data["notify"]
        entries = logic.schedule_for(device, date, end_date)
        try:
            diffs, synthetic_map, diff_contexts = _normalize_schedule_diffs_for_save(
                diffs, entries, device, g.user
            )
        except SlotSaveNormalizationError as err:
            model.db.session.rollback()
            return jsonify(
                {
                    "errors": {
                        str(err.slot_id): [
                            _slot_error_row(
                                err.source, err.code, err.message, blocking=True
                            )
                        ]
                    }
                }
            )

        xs, srs, when, errors = logic.verify_scheduler_diffs(
            diffs,
            entries,
            perms,
            support,
            cur_date,
            cur_hour,
            cur_minute,
            groups,
            members_of_groups,
            g.user,
        )
        if errors is not None:
            mapped_errors = _map_server_errors_to_client_ids(errors, synthetic_map)
            model.db.session.rollback()
            return jsonify({"errors": mapped_errors})

        # update models
        staged = logic.apply_scheduler_diffs(g.user, xs)
        srs_notes = logic.apply_scheduler_sr_diffs(g.user, srs)

        # prepare any notifications
        ens, sns = logic.prepare_notifications(
            send_notifications, when, diffs, srs_notes
        )
        notifications = logic.fmt_notifications(ens, sns)

        # apply the changes then send notifications once they're committed
        for s in staged:
            model.db.session.add(s.entry)
        try:
            model.db.session.commit()
        except SQLAlchemyError as err:
            model.db.session.rollback()
            row = _log_scheduler_save_database_error(err, phase="commit")
            client_ids = select_scheduler_error_client_ids(
                err,
                diff_contexts,
                candidate_refs=[stage.server_ref for stage in staged],
            )
            return jsonify({"errors": _build_error_map_for_client_ids(client_ids, row)})
        notification_results = logic.send_scheduler_notifications(device, notifications)
        try:
            model.db.session.commit()
        except SQLAlchemyError:
            model.db.session.rollback()
            current_app.logger.exception(
                "Failed to commit email audit records for scheduler notifications"
            )

        id_map = {}
        for server_id, client_id in synthetic_map.items():
            id_map[client_id] = int(server_id)
        return jsonify(
            {
                "saved": len(staged),
                "notifications": notification_results,
                "id_map": id_map,
            }
        )

    return {
        "device": device,
        "perms": perms,
        "perms_json": perms_json,
        "start_date": fmt_start_date,
        "end_date": fmt_end_date,
        "days": days,
        "top_row": top_row,
        "clock_warning": clock_warning,
        "min": fmt_min,
        "max": fmt_max,
        "never_entries": never_entries,
        "no_entries": no_entries,
        "support": support,
        "members_of_groups": members_of_groups,
        "groups": groups,
        "selection_groups": selection_groups,
        "groups_json": groups_json,
        "device_groups_json": device_groups_json,
        "off_hours": list(off_hours),
        "off_hour_map": off_hour_map,
        "colors": colors,
        "hours": hours,
        "schedule_load_json": {
            "endpoint": url_for("device_schedule_rows", the_device=device.id),
            "start": fmt_start_date,
            "days": days,
        },
        "cur_date": cur_date,
        "cur_hour": cur_hour,
        "form": form,
        **device_breadcrumb(device),
        **device_subpage_nav(device, perms),
    }


def device_schedule_rows(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    if not (device.active or perms.admin):
        abort(403)

    date, days, end_date, _ = schedule_window_from_request(device)

    hour_arg = request.args.get("hours", "")
    parsed_hours = []
    for h in hour_arg.split(","):
        if h == "":
            continue
        if not re.fullmatch(r"\d{1,2}", h):
            abort(400, f"invalid hour value: {h}")
        n = int(h)
        if n < 0 or n > 23:
            abort(400, f"invalid hour value: {h}")
        parsed_hours.append(n)

    hours = sorted(set(parsed_hours))
    if len(hours) == 0:
        abort(400, "hours query parameter is required")
    if len(hours) > 12:
        abort(400, "hours query parameter may include at most 12 rows per request")

    support = logic.SupportRequestDatalists([], [], [])
    if device.active and perms.edit:
        support = logic.support_request_datalists(device)

    entries = logic.schedule_for_hours(device, date, end_date, hours)
    by_slot = {(e.hour, e.date): e for e in entries}
    days_seq = [date + timedelta(days=n) for n in range(days)]

    cur_date = date
    cur_hour = -1
    try:
        cur_date, cur_hour, _ = logic.db_now()
    except SQLAlchemyError:
        current_app.logger.exception(
            "unable to resolve DB ET clock for scheduler row hydration"
        )

    rows = []
    for hour in hours:
        row_cells = []
        for day in days_seq:
            entry = by_slot.get((hour, day))
            if entry is None:
                row_cells.append(
                    render_template(
                        "partials/schedule_entry_cell.html",
                        x=_slot_stub(day, hour),
                        support=support,
                        cur_date=cur_date,
                        cur_hour=cur_hour,
                    )
                )
                continue
            row_cells.append(
                render_template(
                    "partials/schedule_entry_cell.html",
                    x=entry,
                    support=support,
                    cur_date=cur_date,
                    cur_hour=cur_hour,
                )
            )
        rows.append({"hour": hour, "cells": row_cells})

    return jsonify({"rows": rows})


def device_schedule_next_day(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    if not (device.active or perms.admin):
        abort(403)

    the_start = request.args.get("start")
    if the_start is not None:
        start = logic.parse_date(the_start)
        if start is None:
            abort(400, f"invalid start: {the_start} (must be YYYY-MM-DD date)")
    else:
        start, _ = _db_clock_date()
        if start is None:
            abort(503, DB_CLOCK_WARNING)

    direction = request.args.get("direction")
    if direction is None:
        abort(400, "direction is required")

    try:
        direction = int(direction)
    except ValueError:
        abort(400, f"invalid direction: {direction} (must be -1 or 1)")

    if direction not in (-1, 1):
        abort(400, f"invalid direction: {direction} (must be -1 or 1)")

    found = logic.next_schedule_day(device, start, direction)
    if found is None:
        return jsonify({"date": None})
    return jsonify({"date": logic.fmt_date(found)})


def entry_log(id):
    eid, _, templateid = id.partition("-")
    device = logic.get_device_from_schedid(eid)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    if not (device.active or perms.admin):
        abort(403)

    entries = logic.get_sched_log_entry(eid)

    template = None
    templateObject = logic.get_template_from_templateid(templateid)
    if templateObject is not None:
        template = {
            "id": templateObject.id,
            "label": templateObject.label,
            "hidden": templateObject.hidden,
        }

    return jsonify({"template": template, "entries": entries})


def check_device_tmpl_perms(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    can_edit = perms.admin or (perms.template and device.active)
    if not can_edit:
        abort(403)

    return device, perms


def device_tmpl(the_device):
    device, _ = check_device_tmpl_perms(the_device)

    templates = logic.templates_of_device(device, archived=False)
    reports = logic.inspect_template_compatibility(device, [t.id for t in templates])
    for template in templates:
        template.compatibility = reports.get(
            template.id,
            {
                "blocking": False,
                "can_apply": True,
                "can_save": True,
                "summary": [],
                "issues": [],
            },
        )
    codes = [t.id for t in templates]
    raw_start = logic.get_start_day_of(device)
    chg_by = f"user {g.user.id}"
    warn = ""
    if raw_start is None:
        start = logic.next_sunday()
        warn = (
            f"no templates have been published to {device.label} before, "
            f"so the first template week will begin on Sunday {start}"
        )
    else:
        start = logic.next_sunday_on_or_after(raw_start)
        if start != raw_start:
            warn = (
                f"the next unscheduled day on {device.label} is {raw_start}, "
                f"but template weeks always begin on Sunday, so template application "
                f"will begin on Sunday {start}"
            )
    no_templates = ""
    if len(templates) == 0:
        no_templates = f"no templates have been created for {device.label} yet"

    form = logic.TemplateApplyForm(codes)
    if form.validate_on_submit():
        errs = logic.validate_templates_before_application(device, form.templates.data)
        if len(errs) > 0:
            for err in errs:
                flash(err, category="error")
        else:
            logic.process_template_apply(form, device, start, chg_by)
            flash("templates applied")
            return to("device", the_device=device.id, start=start)

    return {
        "title": f"apply templates to {device.label}",
        "action": my_url(),
        "form": form,
        "warn": warn,
        "templates": templates,
        "no_templates": no_templates,
        "start": start,
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


def template_breadcrumb(
    device: model.Device, tmpl: Optional[model.Template] = None
) -> BreadcrumbLinks:
    out = [
        (device.label, url_for("device", the_device=device.id)),
        ("templates", url_for("device_tmpl", the_device=device.id)),
    ]
    if tmpl is not None:
        out.append(
            (
                f"edit {tmpl.label}",
                url_for(
                    "device_tmpl_schedule_edit",
                    the_device=device.id,
                    the_template=tmpl.id,
                ),
            )
        )
    return breadcrumb(*out)


def template_subpage_nav(device: model.Device) -> SubpageLinks:
    def build_url(name: str) -> str:
        return url_for(f"device_tmpl{name}", the_device=device.id)

    return subpage_nav(
        f"template workflows [{device.label}]",
        [
            (True, "schedule", url_for("device", the_device=device.id)),
            (True, "apply", build_url("")),
            (True, "active", build_url("_list")),
            (True, "inactive", build_url("_archive")),
            (True, "add template", build_url("_add")),
        ],
    )


def device_tmpl_list(the_device):
    device, _ = check_device_tmpl_perms(the_device)
    templates = logic.templates_of_device(device, archived=False)
    reports = logic.inspect_template_compatibility(device, [t.id for t in templates])
    for template in templates:
        template.compatibility = reports.get(
            template.id,
            {
                "blocking": False,
                "can_apply": True,
                "can_save": True,
                "summary": [],
                "issues": [],
            },
        )
    return {
        "title": f"templates of {device.label}",
        "device": device,
        "templates": templates,
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


def device_tmpl_archive(the_device):
    device, _ = check_device_tmpl_perms(the_device)
    templates = logic.templates_of_device(device, archived=True)
    reports = logic.inspect_template_compatibility(device, [t.id for t in templates])
    for template in templates:
        template.compatibility = reports.get(
            template.id,
            {
                "blocking": False,
                "can_apply": False,
                "can_save": True,
                "summary": [],
                "issues": [],
            },
        )
    return {
        "title": f"archived templates of {device.label}",
        "device": device,
        "templates": templates,
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


def device_tmpl_add(the_device):
    device, _ = check_device_tmpl_perms(the_device)

    templates = logic.all_templates_of_device(device)
    form = logic.TemplateMetadataForm(device, templates, create=True)
    if form.validate_on_submit():
        ok, id = logic.create_template(form, device)
        if ok:
            return to(
                "device_tmpl_schedule_edit",
                the_device=form.device.id,
                the_template=id,
            )

    return {
        "title": f"add template to {device.label}",
        "device": device,
        "form": form,
        "action": my_url(),
        "submit": "create",
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


def template_single_subpage_nav(
    device: model.Device, tmpl: model.Template
) -> SubpageLinks:
    def entry(label: str, url_suffix: str) -> tuple[bool, str, str]:
        return (
            True,
            label,
            url_for(
                f"device_tmpl_{url_suffix}_edit",
                the_device=device.id,
                the_template=tmpl.id,
            ),
        )

    return subpage_nav(
        f"template editor [{device.label}]",
        [
            (True, "device schedule", url_for("device", the_device=device.id)),
            (True, "templates", url_for("device_tmpl_list", the_device=device.id)),
            entry("edit schedule", "schedule"),
            entry("edit metadata", "metadata"),
        ],
    )


def device_tmpl_schedule_edit(the_device, the_template):
    device, _ = check_device_tmpl_perms(the_device)
    tmpl = logic.get_template(device, the_template)
    if tmpl is None:
        abort(404)

    entries = logic.get_template_entries(device, tmpl)
    compatibility = logic.inspect_template_compatibility(
        device, [tmpl.id], entries=entries
    )[tmpl.id]
    institutes = logic.get_institutes_datalist()
    members_of_groups = logic.all_member_datalists_by_group(device)
    groups = logic.all_groups_of_device(device)
    device_groups_json = [id for (id, _) in groups]
    grouped_entries = logic.group_template_entries(
        logic.display_template_entries(entries)
    )
    colors = logic.all_group_colors()
    hours = logic.fmt_hours()
    off_hours = list(logic.off_hours())

    form = logic.JsonForm()
    if request.method == "POST":
        if not form.validate():
            # client response must specify payload
            abort(500)
        diffs = form.payload.data["diffs"]

        staged, errors = logic.verify_and_prep_template_diffs(
            diffs, entries, institutes, groups, members_of_groups
        )
        if errors is not None:
            return jsonify({"errors": errors})

        compatibility = logic.inspect_template_compatibility(
            device, [tmpl.id], entries=entries
        )[tmpl.id]
        if compatibility["blocking"]:
            model.db.session.rollback()
            return jsonify(
                {
                    "errors": compatibility["entry_errors"],
                    "template_errors": compatibility["summary"],
                }
            )

        for s in staged:
            model.db.session.add(s)
        model.db.session.commit()
        return jsonify({"saved": len(staged)})

    return {
        "title": f"edit template schedule {device.label}/{tmpl.label}",
        "schedule_label": device.label,
        "entries": grouped_entries,
        "institutes": institutes,
        "groups": groups,
        "device_groups_json": device_groups_json,
        "members_of_groups": members_of_groups,
        "colors": colors,
        "hours": hours,
        "off_hours": off_hours,
        "form": form,
        "template_compatibility": compatibility,
        **template_breadcrumb(device, tmpl),
        **template_single_subpage_nav(device, tmpl),
    }


def device_tmpl_metadata_edit(the_device, the_template):
    device, _ = check_device_tmpl_perms(the_device)
    tmpl = logic.get_template(device, the_template)
    if tmpl is None:
        abort(404)

    form = logic.TemplateMetadataForm(device, [], create=False, obj=tmpl)
    if form.validate_on_submit():
        if logic.process_update_template_metadata(form, tmpl):
            return to(
                "device_tmpl_schedule_edit",
                the_device=form.device.id,
                the_template=tmpl.id,
            )

    return {
        "title": f"edit template {device.label}/{tmpl.label}",
        "device": device,
        "template": tmpl,
        "form": form,
        "action": my_url(),
        "submit": "save",
        **template_breadcrumb(device, tmpl),
        **template_single_subpage_nav(device, tmpl),
    }


def register_entity_routes(
    app,
    *,
    active_user_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    login_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    render_to: Callable[[str], Callable[[Callable[..., Any]], Callable[..., Any]]],
    my_url_fn: Callable[[], str],
    to_fn: Callable[..., Any],
    breadcrumb_fn: Callable[..., BreadcrumbLinks],
    subpage_nav_fn: Callable[[str, List[Tuple[bool, str, str]]], SubpageLinks],
) -> None:
    global _my_url_fn, _to_fn, _breadcrumb_fn, _subpage_nav_fn
    _my_url_fn = my_url_fn
    _to_fn = to_fn
    _breadcrumb_fn = breadcrumb_fn
    _subpage_nav_fn = subpage_nav_fn

    app.add_url_rule(
        "/group/<the_group>",
        view_func=active_user_required(render_to("group")(group)),
    )

    app.add_url_rule(
        "/device/<the_device>",
        methods=["GET", "POST"],
        view_func=login_required(render_to("device")(device)),
    )

    app.add_url_rule(
        "/json/v1/device/<the_device>/schedule-rows",
        view_func=login_required(device_schedule_rows),
    )

    app.add_url_rule(
        "/json/v1/device/<the_device>/schedule-next-day",
        view_func=login_required(device_schedule_next_day),
    )

    app.add_url_rule(
        "/json/v1/log/<id>",
        view_func=login_required(entry_log),
    )

    app.add_url_rule(
        "/device/<the_device>/templates",
        methods=["GET", "POST"],
        view_func=active_user_required(render_to("template_apply")(device_tmpl)),
    )

    app.add_url_rule(
        "/device/<the_device>/templates/list",
        view_func=active_user_required(render_to("templates_list")(device_tmpl_list)),
    )

    app.add_url_rule(
        "/device/<the_device>/templates/archive",
        view_func=active_user_required(
            render_to("templates_list")(device_tmpl_archive)
        ),
    )

    app.add_url_rule(
        "/device/<the_device>/templates/add",
        methods=["GET", "POST"],
        view_func=active_user_required(
            render_to("templates_metadata_edit")(device_tmpl_add)
        ),
    )

    app.add_url_rule(
        "/device/<the_device>/templates/edit/<the_template>",
        methods=["GET", "POST"],
        view_func=active_user_required(
            render_to("templates")(device_tmpl_schedule_edit)
        ),
    )

    app.add_url_rule(
        "/device/<the_device>/templates/edit-metadata/<the_template>",
        methods=["GET", "POST"],
        view_func=active_user_required(
            render_to("templates_metadata_edit")(device_tmpl_metadata_edit)
        ),
    )
