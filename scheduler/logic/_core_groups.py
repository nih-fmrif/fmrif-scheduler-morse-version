from __future__ import annotations

from functools import lru_cache
from typing import Any, List, Literal, Optional, Set, Tuple, cast

from flask_wtf import FlaskForm
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.expression import and_, or_
from sqlalchemy.sql.functions import func
from wtforms import fields, validators, widgets

from scheduler import model
from scheduler.auth.test_session_state import get_auth_test_session_pi_groups

from ._core_shared import Datalist
from ._core_users import get_user
from .rbac_audit_support import constraint_of
from .schedule_editor import _clear_reference_data_cache


def get_group(which: str) -> Optional[model.Group]:
    return model.db.session.get(model.Group, which)


def pi_of_group(group: str) -> str:
    m = model.Membership
    row = model.db.session.scalars(
        select(m).where(m.group == group).where(m.pi)
    ).first()
    return row.user


def change_pi_of_group(group: model.Group, user: model.User) -> None:
    membership = model.PrimaryGroupMember
    model.db.session.execute(delete(membership).where(membership.group == group.id))
    new = membership(group=group.id, user=user.id)
    model.db.session.add(new)


def get_all_groups_with_members(active: bool) -> List[model.Group]:
    statement = (
        select(model.Group)
        .where(model.Group.active == active)
        .where(model.Group.has_membership)
        .order_by(model.Group.label)
    )
    return model.db.session.scalars(statement).all()


def get_groups(which: List[str]) -> List[model.Group]:
    # SQLAlchemy's metaclass confuses mypy here, but runtime behavior is fine.
    id_col = cast(Any, model.Group.id)
    statement = (
        select(model.Group)
        .where(model.Group.active)
        .where(id_col.in_(which))
        .order_by(model.Group.label)
    )
    return model.db.session.scalars(statement).all()


def get_members_of_group(
    group: model.Group, all: bool = False
) -> List[Tuple[str, bool, bool]]:
    statement = (
        select(model.Membership)
        .where(model.Membership.group == group.id)
        .where(model.Membership.user_active)
    )
    if not all:
        statement = statement.where(model.Membership.approved)
    memberships = model.db.session.scalars(statement).all()
    return [(row.user, row.pi, row.approved) for row in memberships]


def remove_user_from_group(user: model.User, group: model.Group) -> None:
    req = model.db.session.get(model.GroupMember, (group.id, user.id))
    if req is None:
        return
    model.db.session.delete(req)


Group_leader_kind = Set[Literal["group_pi", "dev_pi", "admin"]]


def get_group_leader_kind(user: model.User, group: model.Group) -> Group_leader_kind:
    session_pi_groups = get_auth_test_session_pi_groups(user)
    membership = model.Membership
    statement = (
        select(membership)
        .where(membership.user == user.id)
        .where(membership.user_active)
        .where(membership.approved)
        .where(
            or_(
                and_(membership.group == group.id, membership.pi),
                and_(membership.group == "DEV", membership.pi),
                membership.group == "admin",
            )
        )
    )
    result: Group_leader_kind = set()
    for row in model.db.session.scalars(statement).all():
        if row.group == group.id and row.pi:
            result.add("group_pi")
        elif row.group == "DEV" and row.pi:
            result.add("dev_pi")
        elif row.group == "admin":
            result.add("admin")
    if group.id in session_pi_groups:
        result.add("group_pi")
    if "DEV" in session_pi_groups:
        result.add("dev_pi")
    return result


class GroupEditForm(FlaskForm):
    id = fields.StringField(
        label="deptcode",
        validators=[
            validators.InputRequired(),
            validators.Length(
                max=10, message="deptcode must be 10 characters or fewer"
            ),
        ],
        render_kw={"autocomplete": "off", "spellcheck": "false"},
    )
    label = fields.StringField(
        label="label, short",
        validators=[
            validators.InputRequired(),
            validators.Length(
                max=20, message="short label must be 20 characters or fewer"
            ),
        ],
        render_kw={"autocomplete": "off"},
    )
    description = fields.StringField(
        label="label, long",
        validators=[
            validators.InputRequired(),
            validators.Length(
                max=75, message="long label must be 75 characters or fewer"
            ),
        ],
        render_kw={"autocomplete": "off"},
    )
    addr = fields.StringField(
        label="email",
        description="multiple email addresses may be separated by commas",
        render_kw={"multiple": "multiple", "type": "email", "autocomplete": "off"},
    )
    link = fields.URLField(label="link")
    color = fields.StringField(label="legend color", widget=widgets.ColorInput())
    inst = fields.StringField(
        label="institute",
        render_kw={"list": "institutes", "autocomplete": "off", "spellcheck": "false"},
    )
    pi = fields.StringField(
        label="pi",
        description="must be valid AD name of user in database",
        validators=[validators.InputRequired()],
        render_kw={"autocomplete": "off", "spellcheck": "false"},
    )
    active = fields.BooleanField(label="active", default=True)

    def __init__(
        self, group_id, institutes, is_admin=False, create=False, *args, **kwargs
    ):
        if create and not is_admin:
            raise Exception("internal error, illegal state")
        super().__init__(*args, **kwargs)
        self.institutes = institutes
        special = group_id in ("admin", "DEV")
        if not is_admin:
            del self.inst
            del self.active
        elif special:
            del self.active
        if not create:
            del self.pi
            del self.id
        if special:
            del self.color
            del self.inst

    def set_errors_from_exception(self, ex: IntegrityError) -> None:
        prefix, c = constraint_of(ex)
        if prefix == "tlkpdept":
            if c == "pkey":
                self.id.errors.append("this id is already in use by another group")
            elif c == "dept_short_key":
                self.label.errors.append(
                    "this label is already in use by another group"
                )
            elif c == "dept_key":
                self.description.errors.append(
                    "this description is already in use by another group"
                )
            elif c == "valid_color":
                self.color.errors.append("invalid color sent by browser")
            elif c == "inst_fkey":
                self.inst.errors.append("invalid institute selected")


def get_institutes_datalist() -> Datalist:
    return list(_cached_institutes_datalist())


@lru_cache(maxsize=1)
def _cached_institutes_datalist() -> Tuple[Tuple[str, str], ...]:
    institutes = model.db.session.scalars(
        select(model.Inst).where(model.Inst.active)
    ).all()
    rows = []
    for institute in institutes:
        label = institute.label
        if label != institute.id:
            label = f"{institute.label} ({institute.id})"
        rows.append((institute.id, label))
    return tuple(rows)


def update_group(is_admin: bool, group: model.Group, form: GroupEditForm) -> bool:
    group.label = form.label.data
    group.description = form.description.data
    group.addr = form.addr.data
    group.link = form.link.data
    if form.color:
        group.color = form.color.data
    if is_admin:
        if form.inst:
            group.inst = form.inst.data
            if group.inst == "":
                group.inst = None
        if form.active:
            group.active = form.active.data
    model.db.session.add(group)
    try:
        model.db.session.commit()
    except IntegrityError as ex:
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return False
    _clear_reference_data_cache()
    return True


def create_group(form: GroupEditForm) -> bool:
    user = get_user(form.pi.data)
    if user is None:
        form.pi.errors.append("user not found")
        return False
    if not user.active:
        form.pi.errors.append("only active user may be PI")
        return False

    group = model.Group()
    group.id = form.id.data
    group.label = form.label.data
    group.description = form.description.data
    group.color = form.color.data
    group.addr = form.addr.data
    group.link = form.link.data
    group.inst = form.inst.data
    if group.inst == "":
        group.inst = None
    group.active = form.active.data
    model.db.session.add(group)

    membership = model.GroupMember(user=user.id, group=group.id, approved=func.now())
    model.db.session.add(membership)
    pi = model.PrimaryGroupMember(user=user.id, group=group.id)
    model.db.session.add(pi)

    try:
        model.db.session.commit()
    except IntegrityError as ex:
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return False
    _clear_reference_data_cache()
    return True


class GroupPIForm(FlaskForm):
    pi = fields.StringField(
        label="pi",
        validators=[validators.InputRequired()],
        render_kw={"list": "members", "autocomplete": "off", "spellcheck": "false"},
    )

    def __init__(self, members, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.members = zip(members, members)

    def validate_pi(self, pi):
        if any(pi == member[0] for member in self.members):
            raise validators.ValidationError("invalid member selected")

    def set_errors_from_exception(self, ex: IntegrityError) -> None:
        prefix, c = constraint_of(ex)
        if prefix != "primarygroupmember":
            return
        if c == "researchercode_fkey":
            self.pi.errors.append("invalid member selected")
        elif c == "groupmembers_key":
            self.pi.errors.append("user must be member of group")


def process_group_pi_form(
    group: model.Group, form: GroupPIForm
) -> Optional[model.User]:
    user = get_user(form.pi.data)
    if user is None:
        return None

    change_pi_of_group(group, user)
    try:
        model.db.session.commit()
    except IntegrityError as ex:
        model.db.session.rollback()
        form.set_errors_from_exception(ex)
        return None
    return user


__all__ = [
    "GroupEditForm",
    "GroupPIForm",
    "Group_leader_kind",
    "change_pi_of_group",
    "create_group",
    "get_all_groups_with_members",
    "get_group",
    "get_group_leader_kind",
    "get_groups",
    "get_institutes_datalist",
    "get_members_of_group",
    "pi_of_group",
    "process_group_pi_form",
    "remove_user_from_group",
    "update_group",
]
