from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask_wtf import FlaskForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.expression import and_, or_
from wtforms import fields, validators

from scheduler import model
from scheduler.auth.test_session_state import has_auth_test_session_pi_group

from ._core_shared import Datalist, _request_cache_dict
from .rbac_audit_support import constraint_of


def get_device(id: str) -> Optional[model.Device]:
    return model.db.session.get(model.Device, id)


def get_devices(active: bool) -> List[model.Device]:
    statement = (
        select(model.Device)
        .where(model.Device.active == active)
        .order_by(model.Device.label)
    )
    return model.db.session.scalars(statement).all()


class DevicePerms(object):
    def __init__(
        self,
        is_admin: bool,
        is_dev_pi: bool,
        can_edit: bool,
        ud: Optional[model.UserDevice],
    ):
        self._admin = is_admin
        self._dpi = is_dev_pi
        self._edit = can_edit

        self._tmpl = False
        self._slot = False
        self._tech = False
        self._med = False
        self._train = False

        if ud is not None:
            self._tmpl = ud.templates
            self._slot = ud.slot
            self._tech = ud.tech
            self._med = ud.medical
            self._train = ud.training

    @property
    def admin(self) -> bool:
        return self._admin

    @property
    def dev_pi(self) -> bool:
        return self._dpi

    @property
    def doa(self) -> bool:
        return self.dev_pi or self.admin

    @property
    def edit(self) -> bool:
        return self._edit or self.edit_any

    @property
    def edit_any(self) -> bool:
        return self._slot or self.doa

    @property
    def template(self) -> bool:
        return self._tmpl or self.doa

    @property
    def tech(self) -> bool:
        return self._tech or self.doa

    @property
    def medical(self) -> bool:
        return self._med or self.doa

    @property
    def training(self) -> bool:
        return self._train or self.doa


def get_dev_perms(user: model.User, device: model.Device) -> DevicePerms:
    cache: Optional[Dict[Any, Any]] = None
    key: Optional[Tuple[str, str]] = None
    if isinstance(user, model.User) and isinstance(device, model.Device):
        cache = _request_cache_dict("_cached_device_perms")
        key = (user.id, device.id)
        if cache is not None:
            cached = cache.get(key)
            if cached is not None:
                return cached

    if not user.active:
        perms = DevicePerms(False, False, False, None)
        if cache is not None and key is not None:
            cache[key] = perms
        return perms

    is_admin = False
    is_dpi = has_auth_test_session_pi_group(user, "DEV")
    membership = model.Membership
    membership_statement = (
        select(membership)
        .where(membership.user == user.id)
        .where(membership.user_active)
        .where(membership.approved)
        .where(
            or_(
                and_(membership.group == "DEV", membership.pi),
                membership.group == "admin",
            )
        )
    )
    for row in model.db.session.scalars(membership_statement).all():
        if row.group == "DEV" and row.pi:
            is_dpi = True
        elif row.group == "admin":
            is_admin = True

    if is_admin or is_dpi:
        perms = DevicePerms(is_admin, is_dpi, True, None)
        if cache is not None and key is not None:
            cache[key] = perms
        return perms

    membership_groups = (
        select(model.Membership.group)
        .where(model.Membership.user == user.id)
        .where(model.Membership.user_active.is_(True))
        .where(model.Membership.approved.is_(True))
    )
    can_edit = (
        model.db.session.scalar(
            select(model.DeviceGroup.group)
            .where(model.DeviceGroup.device == device.id)
            .where(model.DeviceGroup.group.in_(membership_groups))
            .limit(1)
        )
        is not None
    )

    ud = model.db.session.get(model.UserDevice, (user.id, device.id))
    perms = DevicePerms(False, False, can_edit, ud)
    if cache is not None and key is not None:
        cache[key] = perms
    return perms


class DeviceEditForm(FlaskForm):
    id = fields.StringField(
        label="scannercode",
        validators=[
            validators.InputRequired(),
            validators.Length(
                max=5, message="scannercode must be 5 characters or fewer"
            ),
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
    description = fields.TextAreaField(label="description")
    addr = fields.StringField(
        "email",
        description="multiple email addresses may be separated by commas",
        render_kw={"multiple": "multiple", "type": "email", "autocomplete": "off"},
    )
    tech_addr = fields.StringField(
        "technologist email",
        description="multiple email addresses may be separated by commas",
        render_kw={"multiple": "multiple", "type": "email", "autocomplete": "off"},
    )
    med_addr = fields.StringField(
        "medical email",
        description="multiple email addresses may be separated by commas",
        render_kw={"multiple": "multiple", "type": "email", "autocomplete": "off"},
    )
    train_addr = fields.StringField(
        "training email",
        description="multiple email addresses may be separated by commas",
        render_kw={"multiple": "multiple", "type": "email", "autocomplete": "off"},
    )
    active = fields.BooleanField(label="active", default=True)

    def __init__(self, is_admin=False, create=False, *args, **kwargs):
        if create and not is_admin:
            raise Exception("internal error, illegal state")
        super().__init__(*args, **kwargs)
        if not create:
            del self.id
        if not is_admin:
            del self.active

    def set_errors_from_exception(self, ex: IntegrityError) -> None:
        prefix, c = constraint_of(ex)
        if prefix == "tlkpscanner":
            if c == "pkey":
                self.id.errors.append("this id is already in use by another device")
            elif c == "scanner_key":
                self.label.errors.append(
                    "this label is already in use by another device"
                )


def update_device(is_admin: bool, device: model.Device, form: DeviceEditForm) -> bool:
    device.label = form.label.data
    device.description = form.description.data
    device.addr = form.addr.data
    device.tech_addr = form.tech_addr.data
    device.med_addr = form.med_addr.data
    device.train_addr = form.train_addr.data
    if is_admin:
        device.active = form.active.data
    model.db.session.add(device)
    try:
        model.db.session.commit()
    except IntegrityError as ex:
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return False
    return True


def create_device(form: DeviceEditForm) -> Optional[model.Device]:
    device = model.Device()
    device.id = form.id.data
    device.label = form.label.data
    device.description = form.description.data
    device.addr = form.addr.data
    device.tech_addr = form.tech_addr.data
    device.med_addr = form.med_addr.data
    device.train_addr = form.train_addr.data
    device.active = form.active.data
    model.db.session.add(device)
    try:
        model.db.session.commit()
    except IntegrityError as ex:
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return None
    return device


def groups_of_device(device: model.Device) -> Datalist:
    query = model.db.session.execute(
        select(model.Group.id, model.Group.label)
        .join(model.DeviceGroup, model.DeviceGroup.group == model.Group.id)
        .where(model.Group.department.is_(True))
        .where(model.Group.active.is_(True))
        .where(model.DeviceGroup.device == device.id)
        .order_by(model.Group.id)
    )
    out = []
    for group_id, label in query.fetchall():
        if group_id != label:
            label += f" ({group_id})"
        out.append((group_id, label))
    return out


def groups_not_of_device(device: model.Device) -> Datalist:
    device_groups = select(model.DeviceGroup.group).where(
        model.DeviceGroup.device == device.id
    )
    query = model.db.session.execute(
        select(model.Group.id, model.Group.label)
        .where(model.Group.department.is_(True))
        .where(model.Group.active.is_(True))
        .where(~model.Group.id.in_(device_groups))
        .order_by(model.Group.id)
    )
    out = []
    for group_id, label in query.fetchall():
        if group_id != label:
            label += f" ({group_id})"
        out.append((group_id, label))
    return out


def add_group_to_device(group: str, device: str):
    model.db.session.add(model.DeviceGroup(group=group, device=device))


def remove_group_from_device(group: str, device: str):
    device_group = model.db.session.get(model.DeviceGroup, (device, group))
    if device_group is None:
        return
    model.db.session.delete(device_group)


class AddGroupToDeviceForm(FlaskForm):
    dept = fields.StringField(
        label="department",
        validators=[validators.InputRequired()],
        render_kw={"list": "departments", "autocomplete": "off", "spellcheck": "false"},
    )

    def __init__(self, departments, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.departments = departments

    def validate_dept(self, dept):
        if any(dept.data == department for department in self.departments):
            raise validators.ValidationError("invalid department selected")

    def set_errors_from_exception(self, ex: IntegrityError) -> None:
        prefix, c = constraint_of(ex)
        if prefix == "groupdevice" and c == "deptcode_fkey":
            self.inactive.dept.errors.append("invalid department")


def process_add_group_to_device_form(dev: str, form) -> bool:
    add_group_to_device(form.dept.data, dev)
    try:
        model.db.session.commit()
    except IntegrityError as ex:
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return False
    return True


def get_dev_members_for_device(
    device: model.Device,
) -> Tuple[List[str], List[str]]:
    query = model.db.session.execute(
        select(model.Membership.user, model.UserDevice.device)
        .outerjoin(
            model.UserDevice,
            and_(
                model.UserDevice.user == model.Membership.user,
                model.UserDevice.device == device.id,
            ),
        )
        .where(model.Membership.group == "DEV")
        .where(model.Membership.approved.is_(True))
        .where(model.Membership.user_active.is_(True))
        .order_by(model.Membership.user)
    )
    active, inactive = [], []
    for user, dev in query.fetchall():
        if dev == device.id:
            active.append(user)
        else:
            inactive.append(user)
    return active, inactive


def get_dev_tech_status(user: model.User) -> Tuple[bool, bool]:
    if not user.active:
        return False, False

    is_dev = (
        model.db.session.scalar(
            select(model.Membership.user)
            .where(model.Membership.group == "DEV")
            .where(model.Membership.user == user.id)
            .where(model.Membership.approved.is_(True))
            .where(model.Membership.user_active.is_(True))
            .limit(1)
        )
        is not None
    )
    is_tech = (
        model.db.session.scalar(
            select(model.Technologist.user)
            .where(model.Technologist.user == user.id)
            .where(model.Technologist.approved_on.is_not(None))
            .limit(1)
        )
        is not None
    )
    return is_dev, is_dev and is_tech


def is_technologist(user_id: str) -> bool:
    row = model.db.session.get(model.Technologist, user_id)
    return row is not None and row.approved_on is not None


def get_user_device_special_perms(
    user: model.User, device: model.Device
) -> Tuple[bool, model.UserDevice]:
    ud = model.db.session.get(model.UserDevice, (user.id, device.id))
    if ud is None:
        return True, model.UserDevice(user=user.id, device=device.id)
    return False, ud


class DeviceUserForm(FlaskForm):
    templates = fields.BooleanField(label="use and apply templates")
    slot = fields.BooleanField(label="edit any slot")
    medical = fields.BooleanField(label="respond to medical requests")
    training = fields.BooleanField(label="respond to training requests")
    tech = fields.BooleanField(label="respond to technologist requests")

    rm = fields.SubmitField(
        label="remove from device",
        render_kw={
            "data_confirm_title": "remove user",
            "data_confirm_confirm": "remove",
        },
    )
    cru = fields.SubmitField(label="save")

    def __init__(self, is_new: bool, is_tech: bool, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not is_tech:
            del self.tech
        if is_new:
            del self.rm
            self.cru.label.text = "add"

    def action(self):
        if self.cru.data:
            return "update"
        elif self.rm and self.rm.data:
            return "rm"
        else:
            return ""

    def validate(self, extra_validators=None) -> bool:
        if not FlaskForm.validate(self, extra_validators=extra_validators):
            return False

        action = self.action()
        if action == "":
            return False
        elif action == "rm":
            return True

        checked = any(
            (self.templates.data, self.slot.data, self.medical.data, self.training.data)
        )
        if checked:
            return True
        if self.tech and self.tech.data:
            return True

        self.form_errors.append("at least one permission must be assigned")
        return False

    def populate(self, ud: model.UserDevice):
        self.populate_obj(ud)
        if not self.tech:
            ud.tech = False


__all__ = [
    "AddGroupToDeviceForm",
    "DeviceEditForm",
    "DevicePerms",
    "DeviceUserForm",
    "add_group_to_device",
    "create_device",
    "get_dev_members_for_device",
    "get_dev_perms",
    "get_dev_tech_status",
    "get_device",
    "get_devices",
    "get_user_device_special_perms",
    "groups_not_of_device",
    "groups_of_device",
    "is_technologist",
    "process_add_group_to_device_form",
    "remove_group_from_device",
    "update_device",
]
