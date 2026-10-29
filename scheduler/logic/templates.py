"""Template lifecycle helpers."""

import datetime
from collections import Counter, defaultdict
from types import SimpleNamespace
from typing import Any, DefaultDict, Dict, List, Optional, Set, Tuple, cast

from flask_wtf import FlaskForm
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.functions import func
from wtforms import fields, validators

from scheduler import model

from ._schedule_editor_reference import (
    all_groups_of_device,
    all_member_datalists_by_group,
    support_request_datalists,
)
from ._schedule_editor_shared import Datalist
from .rbac_audit_support import constraint_of

TEMPLATE_CELL_COUNT = 7 * 24
LEGACY_NONE_GROUP = "(none)"
LEGACY_OLD_USER_SUFFIX = "[OLD]"
TEMPLATE_DAY_LABELS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def get_template(
    for_device: model.Device, template_id: str
) -> Optional[model.Template]:
    return model.db.session.get(model.Template, (template_id, for_device.id))


def get_template_from_templateid(templateid: str) -> Optional[model.Template]:
    if templateid == "":
        return None
    entry = model.db.session.get(model.TemplateEntry, templateid)
    if entry is None:
        return None
    return model.db.session.get(model.Template, (entry.template, entry.device))


def templates_of_device(
    device: model.Device, archived: bool = False
) -> List[model.Template]:
    template_model = model.Template
    statement = (
        select(template_model)
        .where(template_model.device == device.id)
        .where(template_model.hidden == archived)
        .order_by(template_model.label)
    )
    return model.db.session.scalars(statement).all()


def all_templates_of_device(device: model.Device) -> Datalist:
    template_model = model.Template
    statement = (
        select(template_model)
        .where(template_model.device == device.id)
        .order_by(template_model.hidden, template_model.label)
    )
    out = []
    for template in model.db.session.scalars(statement).all():
        archived = ""
        if template.hidden:
            archived = " [archived]"
        out.append((template.id, f"{template.label} ({template.id}){archived}"))
    return out


class TemplateMetadataForm(FlaskForm):
    clone_from = fields.StringField(
        label="clone",
        description="prepopulate new template with schedule of an existing template (optional)",
        validators=[validators.Length(min=0, max=1)],
        render_kw={"autocomplete": "off", "spellcheck": "false", "list": "templates"},
    )
    id = fields.StringField(
        label="template code",
        validators=[
            validators.InputRequired(),
            validators.Length(max=1, message="templatecode must be 1 character long"),
        ],
        render_kw={"autocomplete": "off", "spellcheck": "false"},
    )
    label = fields.StringField(
        label="label",
        validators=[
            validators.InputRequired(),
            validators.Length(max=25, message="label must be 25 characters or fewer"),
        ],
        render_kw={"autocomplete": "off"},
    )
    description = fields.TextAreaField(
        label="description",
    )
    hidden = fields.BooleanField(label="archived", default=False)

    def __init__(self, device, templates, create=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device = device
        self.templates = templates
        if not create:
            del self.id
            del self.clone_from

    def validate_clone_from(self, clone) -> None:
        if not clone.data:
            return
        if not any(clone.data == template_id for (template_id, _) in self.templates):
            raise validators.ValidationError("invalid template")

    def set_errors_from_exception(self, ex: IntegrityError) -> None:
        prefix, constraint = constraint_of(ex)
        if prefix != "tbltemplates":
            return
        if constraint == "pkey":
            self.id.errors.append(
                "this id is already in use by another template on this device"
            )
        elif constraint == "scannercode_fkey":
            self.errors.append("form was created improperly, no device to reference")


def process_update_template_metadata(
    form: TemplateMetadataForm, tmpl: model.Template
) -> bool:
    form.populate_obj(tmpl)
    model.db.session.add(tmpl)
    try:
        model.db.session.commit()
    except IntegrityError as ex:
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return False
    return True


def create_template(
    form: TemplateMetadataForm, for_device: model.Device
) -> Tuple[bool, str]:
    tmpl = model.Template()
    form.populate_obj(tmpl)
    tmpl.device = for_device.id

    model.db.session.add(tmpl)
    try:
        model.db.session.flush()
    except IntegrityError as ex:
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return (False, "")

    if form.clone_from.data:
        model.db.session.execute(
            text(
                """
            insert into tbltemplate(scannercode, templatecode, dow, hour, deptcode, researchercode, instcode)
                select :scannercode,
                       :templatecode,
                       dow,
                       hour,
                       nullif(deptcode, :legacy_none_group),
                       researchercode,
                       instcode
                    from tbltemplate where (scannercode, templatecode) = (:scannercode, :orig_templatecode)
            """
            ),
            {
                "scannercode": tmpl.device,
                "templatecode": tmpl.id,
                "orig_templatecode": form.clone_from.data,
                "legacy_none_group": LEGACY_NONE_GROUP,
            },
        )
    else:
        model.db.session.execute(
            text(
                """
            insert into tbltemplate(scannercode, templatecode, dow, hour)
                select :scannercode, :templatecode, dow, hour
                    from
                        generate_series(0, 6) as dow
                    cross join
                        generate_series(0, 23) as hour;
            """
            ),
            {
                "scannercode": tmpl.device,
                "templatecode": tmpl.id,
            },
        )

    try:
        model.db.session.commit()
    except IntegrityError as ex:
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return (False, "")
    return (True, tmpl.id)


def get_template_entries(
    device: model.Device, template: model.Template
) -> List[model.TemplateEntry]:
    entry_model = model.TemplateEntry
    statement = (
        select(entry_model)
        .where(entry_model.device == device.id)
        .where(entry_model.template == template.id)
        .order_by(entry_model.hour, entry_model.dow)
    )
    return model.db.session.scalars(statement).all()


def normalize_template_group(value: Optional[str]) -> Optional[str]:
    if value in (None, "", LEGACY_NONE_GROUP):
        return None
    return value


def display_template_entries(
    entries: List[model.TemplateEntry],
) -> List[SimpleNamespace]:
    display_entries: List[SimpleNamespace] = []
    for entry in entries:
        display_entries.append(
            SimpleNamespace(
                id=entry.id,
                hour=entry.hour,
                dow=entry.dow,
                group=normalize_template_group(entry.group),
                user=entry.user or None,
                inst=entry.inst or None,
            )
        )
    return display_entries


def get_start_day_of(device: model.Device) -> Optional[datetime.date]:
    entry_model = model.ScheduleEntry
    day = model.db.session.scalar(
        select(func.max(entry_model.date)).where(entry_model.device == device.id)
    )
    if day is not None:
        day += datetime.timedelta(days=1)
    return day


def next_sunday() -> datetime.date:
    day = datetime.date.today()
    weekday = day.isoweekday()
    day += datetime.timedelta(days=-weekday, weeks=1)
    return day


def next_sunday_on_or_after(day: datetime.date) -> datetime.date:
    return day + datetime.timedelta(days=(7 - day.isoweekday()) % 7)


class TemplateApplyForm(FlaskForm):
    templates = fields.StringField(
        label="templates",
        description="ordered list of template codes to add to the schedule",
        validators=[validators.InputRequired()],
        render_kw={"autocomplete": "off", "spellcheck": "false"},
    )

    def __init__(self, valid_template_codes: List[str], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.valid_template_codes = set(valid_template_codes)

    def validate_templates(self, templates) -> None:
        if not (set(templates.data) <= self.valid_template_codes):
            raise validators.ValidationError("invalid template code(s)")


def uniq(xs: str) -> List[str]:
    acc = []
    seen = set()
    for value in xs:
        if value not in seen:
            seen.add(value)
            acc.append(value)
    return acc


def _template_validation_context(
    device: model.Device,
) -> Tuple[Set[Optional[str]], Dict[Optional[str], Set[Optional[str]]]]:
    inst_model = model.Inst
    inst_statement = select(inst_model).where(inst_model.active)
    inst: Set[Optional[str]] = {
        inst_entry.id for inst_entry in model.db.session.scalars(inst_statement).all()
    }
    inst.add(None)

    groups: Dict[Optional[str], Set[Optional[str]]] = {None: {None}}
    for group_id, _label in all_groups_of_device(device):
        groups[group_id] = {None}
    member_datalists = all_member_datalists_by_group(device)
    support_datalists = support_request_datalists(device)
    for deptcode, members in member_datalists.items():
        group_members = groups.setdefault(deptcode, {None})
        group_members.update(member_id for (member_id, _) in members)
    groups["training"] = set(member_id for (member_id, _) in support_datalists.training)
    groups["training"].add(None)
    return inst, groups


def _template_cell_label(cell: model.TemplateEntry) -> str:
    day = TEMPLATE_DAY_LABELS[cell.dow]
    return f"{day} {cell.hour:02d}:00"


def inspect_template_compatibility(
    device: model.Device,
    template_ids: List[str],
    entries: Optional[List[model.TemplateEntry]] = None,
) -> Dict[str, Dict[str, Any]]:
    ordered_templates: List[str] = []
    seen: Set[str] = set()
    for template_id in template_ids:
        if template_id not in seen:
            ordered_templates.append(template_id)
            seen.add(template_id)

    if not ordered_templates:
        return {}

    template_model = model.Template
    id_col = cast(Any, template_model.id)
    template_statement = (
        select(template_model)
        .where(template_model.device == device.id)
        .where(id_col.in_(ordered_templates))
    )
    template_by_id = {
        template.id: template
        for template in model.db.session.scalars(template_statement).all()
    }

    entry_map: DefaultDict[str, List[model.TemplateEntry]] = defaultdict(list)
    if entries is None:
        entry_model = model.TemplateEntry
        template_col = cast(Any, entry_model.template)
        entry_statement = (
            select(entry_model)
            .where(entry_model.device == device.id)
            .where(template_col.in_(ordered_templates))
            .order_by(entry_model.template, entry_model.dow, entry_model.hour)
        )
        selected_entries = model.db.session.scalars(entry_statement).all()
    else:
        selected_entries = [entry for entry in entries if entry.template in seen]

    for cell in selected_entries:
        entry_map[cell.template].append(cell)

    inst, groups = _template_validation_context(device)
    reports: Dict[str, Dict[str, Any]] = {}

    for template_id in ordered_templates:
        template = template_by_id.get(template_id)
        issue_values: DefaultDict[str, Set[str]] = defaultdict(set)
        report: Dict[str, Any] = {
            "id": template_id,
            "template": template,
            "issues": [],
            "summary": [],
            "entry_errors": defaultdict(list),
            "blocking": False,
            "can_apply": False,
            "can_save": False,
        }

        def add_issue(
            code: str,
            message: str,
            *,
            entry: Optional[model.TemplateEntry] = None,
            field: Optional[str] = None,
            value: Optional[str] = None,
            blocking: bool = True,
        ) -> None:
            report["issues"].append(
                {
                    "code": code,
                    "message": message,
                    "blocking": blocking,
                    "entry_id": entry.id if entry is not None else None,
                    "hour": entry.hour if entry is not None else None,
                    "dow": entry.dow if entry is not None else None,
                }
            )
            if blocking:
                report["blocking"] = True
            if value not in (None, ""):
                issue_values[code].add(str(value))
            if entry is not None and field is not None and value:
                report["entry_errors"][entry.id].append(
                    {"type": "removed", "key": field, "value": value}
                )

        if template is None:
            add_issue(
                "missing-template",
                f"{template_id} does not exist on {device.label}.",
            )
            report["summary"].append(f"{template_id} does not exist on {device.label}.")
            report["entry_errors"] = {}
            reports[template_id] = report
            continue

        if template.hidden:
            add_issue(
                "archived-template",
                f"{template_id} is archived and cannot be applied.",
                blocking=False,
            )

        cells = entry_map.get(template_id, [])
        if len(cells) != TEMPLATE_CELL_COUNT:
            add_issue(
                "malformed-template",
                f"{template_id} is malformed: {len(cells)} cells instead of {TEMPLATE_CELL_COUNT}.",
            )

        for cell in cells:
            group = normalize_template_group(cell.group)
            user = cell.user or None
            inst_id = cell.inst or None
            when = _template_cell_label(cell)
            stale_member = bool(user and user.endswith(LEGACY_OLD_USER_SUFFIX))

            if inst_id not in inst:
                add_issue(
                    "invalid-institute",
                    f"{template_id} has invalid institute {inst_id!r} at {when}.",
                    entry=cell,
                    field="institute",
                    value=str(inst_id),
                )

            if stale_member:
                add_issue(
                    "legacy-member",
                    f"{template_id} has stale member {user!r} at {when}.",
                    entry=cell,
                    field="member",
                    value=user,
                )

            if group not in groups:
                if cell.group not in (None, ""):
                    add_issue(
                        "invalid-group",
                        f"{template_id} has invalid group {cell.group!r} at {when}.",
                        entry=cell,
                        field="group",
                        value=str(cell.group),
                    )
                continue

            if stale_member:
                continue

            if user not in groups[group]:
                add_issue(
                    "invalid-member",
                    f"{template_id} has invalid member {user!r} at {when}.",
                    entry=cell,
                    field="member",
                    value=user,
                )

        issue_counts = Counter(
            issue["code"] for issue in report["issues"] if issue["blocking"]
        )
        if issue_counts["malformed-template"]:
            report["summary"].append(
                f"{template_id} is malformed and must be rebuilt as a full {TEMPLATE_CELL_COUNT}-cell template."
            )
        if issue_counts["legacy-member"]:
            count = issue_counts["legacy-member"]
            noun = "assignment" if count == 1 else "assignments"
            report["summary"].append(
                f"{template_id} has {count} stale member {noun} that must be repaired before save or apply."
            )
            members = sorted(issue_values["legacy-member"])
            if members:
                report["summary"].append(
                    f"stale members in {template_id}: {', '.join(members)}."
                )
        if issue_counts["invalid-group"]:
            count = issue_counts["invalid-group"]
            noun = "group" if count == 1 else "groups"
            report["summary"].append(
                f"{template_id} has {count} invalid {noun} that must be repaired before save or apply."
            )
            groups_list = sorted(issue_values["invalid-group"])
            if groups_list:
                report["summary"].append(
                    f"unavailable groups in {template_id}: {', '.join(groups_list)}."
                )
        if issue_counts["invalid-member"]:
            count = issue_counts["invalid-member"]
            noun = "member" if count == 1 else "members"
            report["summary"].append(
                f"{template_id} has {count} invalid {noun} that must be repaired before save or apply."
            )
            members = sorted(issue_values["invalid-member"])
            if members:
                report["summary"].append(
                    f"unavailable members in {template_id}: {', '.join(members)}."
                )
        if issue_counts["invalid-institute"]:
            count = issue_counts["invalid-institute"]
            noun = "institute" if count == 1 else "institutes"
            report["summary"].append(
                f"{template_id} has {count} invalid {noun} that must be repaired before save or apply."
            )
            institutes = sorted(issue_values["invalid-institute"])
            if institutes:
                report["summary"].append(
                    f"unavailable institutes in {template_id}: {', '.join(institutes)}."
                )
        if not report["summary"] and template.hidden:
            report["summary"].append(
                f"{template_id} is archived and cannot be applied."
            )

        report["entry_errors"] = {
            entry_id: issues
            for entry_id, issues in sorted(
                report["entry_errors"].items(), key=lambda pair: pair[0]
            )
        }
        report["can_save"] = not report["blocking"]
        report["can_apply"] = not template.hidden and not report["blocking"]
        reports[template_id] = report

    return reports


def validate_templates_before_application(device: model.Device, templates: str):
    ordered_templates = uniq(templates)
    errs = []

    if len(ordered_templates) == 0:
        errs.append("no templates to apply")
        return errs

    reports = inspect_template_compatibility(device, ordered_templates)
    for template_id in ordered_templates:
        report = reports.get(template_id)
        if report is None:
            errs.append("invalid template codes provided")
            continue
        if any(issue["code"] == "missing-template" for issue in report["issues"]):
            errs.append("invalid template codes provided")
            continue
        errs.extend(report["summary"])
    return errs


def process_template_apply(
    form: TemplateApplyForm, device: model.Device, start: datetime.date, chg_by: str
):
    model.db.session.execute(
        text(
            """
        insert into tblsched(
            scannercode,
            templateid,
            scheddate,
            scheddow,
            schedhour,
            deptcode,
            orig_deptcode,
            researchercode,
            chg_by,
            orig_instcode)
        select
            scannercode,
            templateid,
            -- add dow+(1 week for each template after the first) days to the start date
            :start_date + dow::integer + dow_offset as scheddate,
            dow scheddow,
            hour schedhour,
            nullif(deptcode, :legacy_none_group),
            nullif(deptcode, :legacy_none_group) orig_deptcode,
            researchercode,
            :chg_by as chg_by,
            instcode orig_instcode
        from
            (
                -- assign each template 7*n for n=0, 1, 2, ..., len(templates)-1
                select 7*(row_number() over () - 1)::integer as dow_offset, *
                from unnest(:templates) as tc
            ) vars
        inner join
            tbltemplate tmpl on (scannercode, templatecode) = (:device, tc)
        """
        ),
        {
            "templates": list(form.templates.data),
            "device": device.id,
            "start_date": start,
            "chg_by": chg_by,
            "legacy_none_group": LEGACY_NONE_GROUP,
        },
    )
    model.db.session.commit()


__all__ = [
    "TemplateMetadataForm",
    "TemplateApplyForm",
    "get_template",
    "get_template_from_templateid",
    "templates_of_device",
    "all_templates_of_device",
    "create_template",
    "display_template_entries",
    "get_template_entries",
    "get_start_day_of",
    "inspect_template_compatibility",
    "next_sunday",
    "next_sunday_on_or_after",
    "normalize_template_group",
    "uniq",
    "validate_templates_before_application",
    "process_template_apply",
    "process_update_template_metadata",
]
