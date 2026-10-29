from __future__ import annotations

from typing import Any, Callable, Optional

from flask import abort, flash, g, jsonify, request, url_for

import scheduler.logic.core as core_logic
import scheduler.logic.schedule_editor as logic
import scheduler.logic.templates as template_logic
from scheduler import model

from ._entity_route_common import (
    BreadcrumbLinks,
    SubpageLinks,
    breadcrumb,
    my_url,
    subpage_nav,
    to,
)


def check_device_tmpl_perms(the_device):
    device = core_logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = core_logic.get_dev_perms(g.user, device)
    can_edit = perms.admin or (perms.template and device.active)
    if not can_edit:
        abort(403)

    return device, perms


def template_breadcrumb(
    device: model.Device, tmpl: Optional[model.Template] = None
) -> BreadcrumbLinks:
    trail = [
        (device.label, url_for("device", the_device=device.id)),
        ("templates", url_for("device_tmpl", the_device=device.id)),
    ]
    if tmpl is not None:
        trail.append(
            (
                f"edit {tmpl.label}",
                url_for(
                    "device_tmpl_schedule_edit",
                    the_device=device.id,
                    the_template=tmpl.id,
                ),
            )
        )
    return breadcrumb(*trail)


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


def device_tmpl(the_device):
    device, _ = check_device_tmpl_perms(the_device)

    templates = template_logic.templates_of_device(device, archived=False)
    reports = template_logic.inspect_template_compatibility(
        device, [template.id for template in templates]
    )
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
    codes = [template.id for template in templates]
    raw_start = template_logic.get_start_day_of(device)
    chg_by = f"user {g.user.id}"
    warn = ""
    if raw_start is None:
        start = template_logic.next_sunday()
        warn = (
            f"no templates have been published to {device.label} before, "
            f"so the first template week will begin on Sunday {start}"
        )
    else:
        start = template_logic.next_sunday_on_or_after(raw_start)
        if start != raw_start:
            warn = (
                f"the next unscheduled day on {device.label} is {raw_start}, "
                f"but template weeks always begin on Sunday, so template application "
                f"will begin on Sunday {start}"
            )
    no_templates = ""
    if len(templates) == 0:
        no_templates = f"no templates have been created for {device.label} yet"

    form = template_logic.TemplateApplyForm(codes)
    if form.validate_on_submit():
        errs = template_logic.validate_templates_before_application(
            device, form.templates.data
        )
        if len(errs) > 0:
            for err in errs:
                flash(err, category="error")
        else:
            template_logic.process_template_apply(form, device, start, chg_by)
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


def device_tmpl_list(the_device):
    device, _ = check_device_tmpl_perms(the_device)
    templates = template_logic.templates_of_device(device, archived=False)
    reports = template_logic.inspect_template_compatibility(
        device, [template.id for template in templates]
    )
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
    templates = template_logic.templates_of_device(device, archived=True)
    reports = template_logic.inspect_template_compatibility(
        device, [template.id for template in templates]
    )
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

    templates = template_logic.all_templates_of_device(device)
    form = template_logic.TemplateMetadataForm(device, templates, create=True)
    if form.validate_on_submit():
        ok, template_id = template_logic.create_template(form, device)
        if ok:
            return to(
                "device_tmpl_schedule_edit",
                the_device=form.device.id,
                the_template=template_id,
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
    tmpl = template_logic.get_template(device, the_template)
    if tmpl is None:
        abort(404)

    entries = template_logic.get_template_entries(device, tmpl)
    compatibility = template_logic.inspect_template_compatibility(
        device, [tmpl.id], entries=entries
    )[tmpl.id]
    institutes = core_logic.get_institutes_datalist()
    members_of_groups = logic.all_member_datalists_by_group(device)
    groups = logic.all_groups_of_device(device)
    device_groups_json = [group_id for (group_id, _) in groups]
    grouped_entries = logic.group_template_entries(
        template_logic.display_template_entries(entries)
    )
    colors = logic.all_group_colors()
    hours = logic.fmt_hours()
    off_hours = list(logic.off_hours())

    form = logic.JsonForm()
    if request.method == "POST":
        if not form.validate():
            abort(500)
        diffs = form.payload.data["diffs"]

        staged, errors = logic.verify_and_prep_template_diffs(
            diffs, entries, institutes, groups, members_of_groups
        )
        if errors is not None:
            return jsonify({"errors": errors})

        compatibility = template_logic.inspect_template_compatibility(
            device, [tmpl.id], entries=entries
        )[tmpl.id]
        if compatibility["blocking"]:
            staged_ids = {staged_entry.id for staged_entry in staged}
            selected_errors = {
                entry_id: issues
                for entry_id, issues in compatibility["entry_errors"].items()
                if entry_id in staged_ids
            }
            if selected_errors:
                model.db.session.rollback()
                return jsonify(
                    {
                        "errors": selected_errors,
                        "template_errors": compatibility["summary"],
                    }
                )

        for staged_entry in staged:
            model.db.session.add(staged_entry)
        model.db.session.commit()
        payload = {"saved": len(staged)}
        if compatibility["blocking"]:
            payload["template_errors"] = compatibility["summary"]
        return jsonify(payload)

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
    tmpl = template_logic.get_template(device, the_template)
    if tmpl is None:
        abort(404)

    form = template_logic.TemplateMetadataForm(device, [], create=False, obj=tmpl)
    if form.validate_on_submit():
        if template_logic.process_update_template_metadata(form, tmpl):
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


def register_template_routes(
    app,
    *,
    active_user_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    render_to: Callable[[str], Callable[[Callable[..., Any]], Callable[..., Any]]],
) -> None:
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
