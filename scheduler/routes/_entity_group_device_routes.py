from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Callable

from flask import abort, current_app, g, jsonify, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

import scheduler.logic.admin_issues as admin_issue_logic
import scheduler.logic.core as core_logic
import scheduler.logic.notifications as notification_logic
import scheduler.logic.schedule_editor as logic
import scheduler.logic.templates as template_logic
from scheduler import model
from scheduler.scheduler_save_error_attribution import select_scheduler_error_client_ids

from ._entity_route_common import (
    DB_CLOCK_WARNING,
    BreadcrumbLinks,
    SlotSaveNormalizationError,
    SubpageLinks,
    _build_error_map_for_client_ids,
    _db_clock_date,
    _log_scheduler_save_database_error,
    _map_server_errors_to_client_ids,
    _normalize_schedule_diffs_for_save,
    _slot_error_row,
    _slot_stub,
    breadcrumb,
    schedule_window_from_request,
    subpage_nav,
)


def group_subpage_nav(
    group: model.Group, su: core_logic.Group_leader_kind
) -> SubpageLinks:
    _ = su
    return subpage_nav(
        "group",
        [
            (True, f"view [{group.label}]", url_for("group", the_group=group.id)),
        ],
    )


def group_breadcrumb(group: model.Group) -> BreadcrumbLinks:
    return breadcrumb((group.label, url_for("group", the_group=group.id)))


def group(the_group):
    group = core_logic.get_group(the_group)
    if group is None:
        abort(404)

    su = core_logic.get_group_leader_kind(g.user, group)

    if not group.active:
        abort(403)

    members = core_logic.get_members_of_group(group)

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


def device_subpage_nav(
    device: model.Device, perms: core_logic.DevicePerms
) -> SubpageLinks:
    def can(permission: bool) -> bool:
        return perms.admin or (permission and device.active)

    device_id = device.id
    return subpage_nav(
        f"device [{device.label}]",
        [
            (True, "schedule", url_for("device", the_device=device_id)),
            (
                can(perms.template),
                "templates",
                url_for("device_tmpl", the_device=device_id),
            ),
        ],
    )


def device(the_device):
    device = core_logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = core_logic.get_dev_perms(g.user, device)

    if not (device.active or perms.admin):
        abort(403)

    date, days, end_date, clock_warning = schedule_window_from_request(device)

    min_date, max_date = logic.device_schedule_extreme_dates(device)

    fmt_start_date = logic.fmt_date(date)
    fmt_end_date = logic.fmt_date(end_date)
    fmt_min = ""
    fmt_max = ""
    if min_date is not None:
        fmt_min = logic.fmt_date(min_date)
        fmt_max = logic.fmt_date(max_date)

    off_hours = logic.off_hours()
    used_hours = logic.schedule_used_hours_for(device, date, end_date)
    has_entries_for_range = len(used_hours) > 0
    off_hours.difference_update(used_hours)
    off_hour_runs = logic.group_off_hours_into_runs(off_hours)
    off_hour_map = logic.convert_off_hour_runs_into_map(off_hour_runs)

    no_entries = ""
    never_entries = ""
    if not has_entries_for_range:
        if min_date is None:
            never_entries = "this device has not yet had any entries scheduled on it"
        else:
            no_entries = (
                f"no entries scheduled for {fmt_start_date}. "
                f"All entries are between {fmt_min} and {fmt_max}"
            )

    colors = logic.all_group_colors()

    support = logic.SupportRequestDatalists([], [], [])
    members_of_groups = {}
    groups = []
    selection_groups = []
    device_groups = logic.all_groups_of_device(device)
    can_fulfill_support = perms.tech or perms.medical or perms.training

    if device.active and (perms.edit or can_fulfill_support):
        support = logic.support_request_datalists(device)

        if perms.edit:
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

    perms_json = {
        "booking_edit": perms.edit,
        "booking_edit_any": perms.edit_any,
        "support_fulfillment": {
            "tech": perms.tech,
            "medical": perms.medical,
            "training": perms.training,
        },
        # Legacy aliases retained while client code migrates.
        "edit": perms.edit,
        "edit_any": perms.edit_any,
        "tech": perms.tech,
        "medical": perms.medical,
        "training": perms.training,
    }
    groups_json = [group_id for (group_id, _) in groups]
    device_groups_json = [group_id for (group_id, _) in device_groups]

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
            f"({header_months[(date + timedelta(days=n)).month - 1]}-"
            f"{(date + timedelta(days=n)).day:02d})"
            if n == 0
            else f"{header_weekdays[(date + timedelta(days=n)).weekday()]} "
            f"({header_months[(date + timedelta(days=n)).month - 1]}-"
            f"{(date + timedelta(days=n)).day:02d})"
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
            abort(403)
        if not form.validate():
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

        if len(diffs) == 0:
            model.db.session.rollback()
            return jsonify({"saved": 0, "notifications": [], "id_map": {}})

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

        staged = logic.apply_scheduler_diffs(g.user, xs)
        srs_notes = logic.apply_scheduler_sr_diffs(g.user, srs)

        ens, sns = notification_logic.prepare_notifications(
            send_notifications, when, diffs, srs_notes
        )
        notifications = notification_logic.fmt_notifications(ens, sns)

        for staged_entry in staged:
            model.db.session.add(staged_entry.entry)
        try:
            model.db.session.commit()
        except SQLAlchemyError as err:
            model.db.session.rollback()
            row = _log_scheduler_save_database_error(err, phase="commit")
            try:
                admin_issue_logic.upsert_scheduler_save_failure_issue(
                    err,
                    actor=g.user.id,
                    device_id=device.id,
                    device_label=device.label,
                    source=str(row["source"]),
                    code=str(row["code"]),
                    client_message=str(row["message"]),
                    href=url_for("device", the_device=device.id),
                )
                model.db.session.commit()
            except SQLAlchemyError:
                model.db.session.rollback()
                current_app.logger.exception(
                    "Failed to persist admin issue for scheduler database rejection"
                )
            client_ids = select_scheduler_error_client_ids(
                err,
                diff_contexts,
                candidate_refs=[stage.server_ref for stage in staged],
            )
            return jsonify({"errors": _build_error_map_for_client_ids(client_ids, row)})
        notification_results = notification_logic.send_scheduler_notifications(
            device, notifications, actor=g.user.id
        )
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
    device = core_logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = core_logic.get_dev_perms(g.user, device)
    if not (device.active or perms.admin):
        abort(403)

    date, days, end_date, _ = schedule_window_from_request(device)

    hour_arg = request.args.get("hours", "")
    parsed_hours = []
    for hour in hour_arg.split(","):
        if hour == "":
            continue
        if not re.fullmatch(r"\d{1,2}", hour):
            abort(400, f"invalid hour value: {hour}")
        value = int(hour)
        if value < 0 or value > 23:
            abort(400, f"invalid hour value: {hour}")
        parsed_hours.append(value)

    hours = sorted(set(parsed_hours))
    if len(hours) == 0:
        abort(400, "hours query parameter is required")
    if len(hours) > 12:
        abort(400, "hours query parameter may include at most 12 rows per request")

    support = logic.SupportRequestDatalists([], [], [])
    if device.active and (perms.edit or perms.tech or perms.medical or perms.training):
        support = logic.support_request_datalists(device)

    entries = logic.schedule_for_hours(device, date, end_date, hours)
    by_slot = {(entry.hour, entry.date): entry for entry in entries}
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
    device = core_logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = core_logic.get_dev_perms(g.user, device)
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

    perms = core_logic.get_dev_perms(g.user, device)
    if not (device.active or perms.admin):
        abort(403)

    entries = logic.get_sched_log_entry(eid)

    template = None
    template_object = template_logic.get_template_from_templateid(templateid)
    if template_object is not None:
        template = {
            "id": template_object.id,
            "label": template_object.label,
            "hidden": template_object.hidden,
        }

    return jsonify({"template": template, "entries": entries})


def register_group_and_device_routes(
    app,
    *,
    active_user_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    login_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    render_to: Callable[[str], Callable[[Callable[..., Any]], Callable[..., Any]]],
) -> None:
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
