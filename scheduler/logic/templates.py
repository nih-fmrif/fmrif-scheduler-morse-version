"""Template lifecycle helpers."""

import datetime
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Optional, Set, Tuple, cast

from flask_wtf import FlaskForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.functions import func
from wtforms import fields, validators

from scheduler import model

from .rbac_audit_support import constraint_of
from .schedule_editor import (
    Datalist,
    all_member_datalists_by_group,
    support_request_datalists,
)


def get_template(
    for_device: model.Device, template_id: str
) -> Optional[model.Template]:
    return model.Template.query.get((template_id, for_device.id))


def get_template_from_templateid(templateid: str) -> Optional[model.Template]:
    if templateid == "":
        return None
    entry = model.TemplateEntry.query.get(templateid)
    if entry is None:
        return None
    return model.Template.query.get((entry.template, entry.device))


def templates_of_device(
    device: model.Device, archived: bool = False
) -> List[model.Template]:
    template_model = model.Template
    query = (
        template_model.query.filter(template_model.device == device.id)
        .filter(template_model.hidden == archived)
        .order_by(template_model.label)
    )
    return query.all()


def all_templates_of_device(device: model.Device) -> Datalist:
    template_model = model.Template
    query = template_model.query.filter(template_model.device == device.id).order_by(
        template_model.hidden, template_model.label
    )
    out = []
    for template in query.all():
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
            """
            insert into tbltemplate(scannercode, templatecode, dow, hour, deptcode, researchercode, instcode)
                select :scannercode, :templatecode, dow, hour, deptcode, researchercode, instcode
                    from tbltemplate where (scannercode, templatecode) = (:scannercode, :orig_templatecode)
            """,
            {
                "scannercode": tmpl.device,
                "templatecode": tmpl.id,
                "orig_templatecode": form.clone_from.data,
            },
        )
    else:
        model.db.session.execute(
            """
            insert into tbltemplate(scannercode, templatecode, dow, hour)
                select :scannercode, :templatecode, dow, hour
                    from
                        generate_series(0, 6) as dow
                    cross join
                        generate_series(0, 23) as hour;
            """,
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
    query = entry_model.query
    query = query.filter(entry_model.device == device.id)
    query = query.filter(entry_model.template == template.id)
    query = query.order_by(entry_model.hour, entry_model.dow)
    return query.all()


def get_start_day_of(device: model.Device) -> Optional[datetime.date]:
    entry_model = model.ScheduleEntry
    day = (
        model.db.session.query(func.max(entry_model.date))
        .filter(entry_model.device == device.id)
        .scalar()
    )
    if day is not None:
        day += datetime.timedelta(days=1)
    return day


def next_sunday() -> datetime.date:
    day = datetime.date.today()
    weekday = day.isoweekday()
    day += datetime.timedelta(days=-weekday, weeks=1)
    return day


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


def validate_templates_before_application(device: model.Device, templates: str):
    ordered_templates = uniq(templates)
    errs = []

    if len(ordered_templates) == 0:
        errs.append("no templates to apply")
        return errs

    template_model = model.Template
    id_col = cast(Any, template_model.id)
    query = (
        template_model.query.filter(template_model.device == device.id)
        .filter(id_col.in_(ordered_templates))
        .filter(template_model.hidden.is_(False))
    )
    template_count = query.count()
    if template_count != len(ordered_templates):
        errs.append("invalid template codes provided")
        if template_count == 0:
            return errs

    has_invalid: Set[str] = set()
    cell_count: DefaultDict[str, int] = defaultdict(int)

    inst_model = model.Inst
    query = inst_model.query.filter(inst_model.active)
    inst: Set[Optional[str]] = set(inst_entry.id for inst_entry in query.all())
    inst.add(None)

    groups: Dict[Optional[str], Set[Optional[str]]] = {None: {None}}
    member_datalists = all_member_datalists_by_group(device)
    support_datalists = support_request_datalists(device)
    for deptcode, members in member_datalists.items():
        group_members: Set[Optional[str]] = set(member_id for (member_id, _) in members)
        group_members.add(None)
        groups[deptcode] = group_members
    groups["training"] = set(member_id for (member_id, _) in support_datalists.training)
    groups["training"].add(None)

    entry_model = model.TemplateEntry
    template_col = cast(Any, entry_model.template)
    query = entry_model.query.filter(entry_model.device == device.id).filter(
        template_col.in_(ordered_templates)
    )

    for cell in query.all():
        template_id = cell.template
        cell_count[template_id] += 1
        if cell.inst not in inst:
            has_invalid.add(template_id)
        elif not (cell.group in groups and cell.user in groups[cell.group]):
            has_invalid.add(template_id)

    for key, value in sorted(cell_count.items(), key=lambda pair: pair[0]):
        if value != 7 * 24:
            errs.append(f"{key} malformed: has {value} entries instead of {7 * 24}")

    for template_id in sorted(has_invalid):
        errs.append(f"{template_id} has invalid entries")

    return errs


def process_template_apply(
    form: TemplateApplyForm, device: model.Device, start: datetime.date, chg_by: str
):
    model.db.session.execute(
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
            deptcode,
            deptcode orig_deptcode,
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
        """,
        {
            "templates": list(form.templates.data),
            "device": device.id,
            "start_date": start,
            "chg_by": chg_by,
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
    "get_template_entries",
    "get_start_day_of",
    "next_sunday",
    "uniq",
    "validate_templates_before_application",
    "process_template_apply",
    "process_update_template_metadata",
]
