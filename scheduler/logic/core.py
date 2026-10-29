import datetime
import hashlib
import re
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, cast

from flask import g
from flask_wtf import FlaskForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.expression import and_, or_
from sqlalchemy.sql.functions import func
from wtforms import fields, validators, widgets

from scheduler import model

from .rbac_audit_support import EMAIL_STATUS_NONE, EMAIL_STATUS_VALUES, constraint_of
from .schedule_editor import _clear_reference_data_cache

_MAX_USER_ID_LENGTH = 20
_USER_ID_PATTERN = re.compile(r"[^a-z0-9_-]+")
Datalist = List[Tuple[str, str]]


def _request_cache_dict(name: str) -> Optional[Dict[Any, Any]]:
    try:
        cache = getattr(g, name)
    except RuntimeError:
        return None
    except AttributeError:
        cache = None
    if cache is None:
        cache = {}
        setattr(g, name, cache)
    return cache


def normalize_name(name: str) -> str:
    if "," in name:
        last, first = [s.strip() for s in name.split(",", 1)]
        return f"{first} {last}"
    return name.strip()


def record_tech_join_request(user: model.User) -> model.Technologist:
    r = model.Technologist.query.get(user.id)
    if r is None:
        r = model.Technologist(
            user=user.id,
            applied_on=func.now(),
            approved_on=None,
            email_status=EMAIL_STATUS_NONE,
        )
    else:
        r.applied_on = func.now()
        r.approved_on = None
        if (r.email_status or "").strip() not in EMAIL_STATUS_VALUES:
            r.email_status = EMAIL_STATUS_NONE
    model.db.session.add(r)
    return r


class JoinForm(FlaskForm):
    group = fields.StringField(
        label="department",
        validators=[validators.InputRequired()],
        render_kw={"list": "departments", "autocomplete": "off", "spellcheck": "false"},
    )

    def __init__(self, departments, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.departments = departments

    def set_errors_from_exception(self, ex: IntegrityError) -> None:
        prefix, c = constraint_of(ex)
        if prefix == "groupmembers" and c == "deptcode_fkey":
            self.group.errors.append("invalid department selected")


def show_tech_join_form(user: model.User) -> bool:
    if not isinstance(user, model.User):
        return False
    cache = _request_cache_dict("_cached_show_tech_join_form")
    if cache is not None:
        cached = cache.get(user.id)
        if cached is not None:
            return cached

    # return a row if user is in DEV unless they have already applied
    q = model.db.session.execute(
        """
        select researchercode from groupmembers G
        where G.deptcode = 'DEV'
        and G.researchercode = :user
        and approved is not null
        except
        select researchercode from technologist T
        where T.researchercode = :user
        """,
        {"user": user.id},
    )
    value = q.first() is not None
    if cache is not None:
        cache[user.id] = value
    return value


def record_join_form(form: JoinForm, user: model.User, group: str) -> bool:
    r = model.GroupMember(user=user.id, group=group)
    model.db.session.add(r)
    try:
        model.db.session.commit()
    except IntegrityError as ex:
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return False
    return True


def add_admin(user: model.User):
    r = model.GroupMember(user=user.id, group="admin", approved=func.now())
    model.db.session.add(r)


def get_join_request(
    user: model.User, group: model.Group
) -> Optional[model.GroupMember]:
    return model.GroupMember.query.get((group.id, user.id))


def get_pending_tech_join_request(user: model.User) -> Optional[model.Technologist]:
    req = model.Technologist.query.get(user.id)
    if req is None:
        return None
    if req.approved_on is not None:
        return None
    return req


def handle_join_request(approved: bool, req: model.GroupMember) -> None:
    if not approved:
        model.db.session.delete(req)
        return

    req.approved = func.now()
    model.db.session.add(req)


def handle_tech_join_request(approved: bool, req: model.Technologist) -> None:
    if not approved:
        model.db.session.delete(req)
        return

    req.approved_on = func.now()
    model.db.session.add(req)


def get_user(user: str) -> Optional[model.User]:
    return model.User.query.get(user)


def _user_id_from_value(user: Any) -> str:
    return str(getattr(user, "id", "") or "").strip()


def _user_is_active(user: Any) -> bool:
    return bool(getattr(user, "active", False))


def _normalize_user_id(value: str) -> str:
    token = _USER_ID_PATTERN.sub("-", (value or "").strip().lower()).strip("-")
    return token[:_MAX_USER_ID_LENGTH]


def scoped_user_id_from_identifier(identifier: str) -> str:
    normalized_identifier = (identifier or "").strip().lower()
    local_part = normalized_identifier.split("@", 1)[0]
    local_token = _normalize_user_id(local_part) or "user"
    digest = hashlib.sha256(normalized_identifier.encode("utf-8")).hexdigest()[:6]
    max_local_len = _MAX_USER_ID_LENGTH - len(digest) - 1
    if max_local_len <= 0:
        return digest[:_MAX_USER_ID_LENGTH]
    return f"{local_token[:max_local_len]}-{digest}"


def _sync_user_profile(
    user: model.User, normalized_mail: str, normalized_name: str
) -> model.User:
    changed = False
    if normalized_mail and user.addr != normalized_mail:
        user.addr = normalized_mail
        changed = True
    if normalized_name and user.label != normalized_name:
        user.label = normalized_name
        changed = True
    if changed:
        model.db.session.add(user)
    return user


def _try_rekey_user_primary_id(old_id: str, new_id: str) -> bool:
    if old_id == new_id:
        return True
    try:
        with model.db.session.begin_nested():
            record = model.User.query.get(old_id)
            if record is None or model.User.query.get(new_id) is not None:
                return False
            record.id = new_id
            model.db.session.flush()
        return True
    except IntegrityError:
        return False


def _rekey_user_foreign_keys(old_id: str, new_id: str) -> None:
    if old_id == new_id:
        return

    memberships = model.GroupMember.query.filter_by(user=old_id).all()
    for row in memberships:
        existing = model.GroupMember.query.get((row.group, new_id))
        if existing is not None:
            if existing.approved is None and row.approved is not None:
                existing.approved = row.approved
                model.db.session.add(existing)
            model.db.session.delete(row)
            continue
        row.user = new_id
        model.db.session.add(row)

    primary_memberships = model.PrimaryGroupMember.query.filter_by(user=old_id).all()
    for row in primary_memberships:
        existing = model.PrimaryGroupMember.query.get((row.group, new_id))
        if existing is not None:
            model.db.session.delete(row)
            continue
        row.user = new_id
        model.db.session.add(row)

    technologist = model.Technologist.query.get(old_id)
    if technologist is not None:
        if model.Technologist.query.get(new_id) is not None:
            model.db.session.delete(technologist)
        else:
            technologist.user = new_id
            model.db.session.add(technologist)

    permissions = model.UserDevice.query.filter_by(user=old_id).all()
    for row in permissions:
        existing = model.UserDevice.query.get((new_id, row.device))
        if existing is not None:
            existing.templates = bool(existing.templates or row.templates)
            existing.slot = bool(existing.slot or row.slot)
            existing.tech = bool(existing.tech or row.tech)
            existing.medical = bool(existing.medical or row.medical)
            existing.training = bool(existing.training or row.training)
            model.db.session.add(existing)
            model.db.session.delete(row)
            continue
        row.user = new_id
        model.db.session.add(row)

    model.ScheduleEntry.query.filter_by(user=old_id).update(
        {"user": new_id}, synchronize_session=False
    )
    model.TemplateEntry.query.filter_by(user=old_id).update(
        {"user": new_id}, synchronize_session=False
    )
    model.SupportRequest.query.filter_by(filed_by=old_id).update(
        {"filed_by": new_id}, synchronize_session=False
    )
    model.SupportRequest.query.filter_by(fulfilled_by=old_id).update(
        {"fulfilled_by": new_id}, synchronize_session=False
    )
    model.SupportRequest.query.filter_by(modified_by=old_id).update(
        {"modified_by": new_id}, synchronize_session=False
    )


def _migrate_user_identity(
    old_user: model.User, new_id: str, normalized_mail: str, normalized_name: str
) -> model.User:
    old_id = old_user.id
    if old_id == new_id:
        return _sync_user_profile(old_user, normalized_mail, normalized_name)

    if _try_rekey_user_primary_id(old_id, new_id):
        # Some test/local DB backends may not enforce ON UPDATE CASCADE consistently.
        # Ensure dependent rows are rewritten even when primary-key rekey succeeds.
        _rekey_user_foreign_keys(old_id, new_id)
        migrated = model.User.query.get(new_id)
        if migrated is None:
            raise RuntimeError(f"Failed to migrate user id from {old_id} to {new_id}")
        return _sync_user_profile(migrated, normalized_mail, normalized_name)

    target = model.User.query.get(new_id)
    if target is None:
        model.db.session.execute(
            """
            insert into tlkpresearcher(researchercode, name, email, active, chg_at)
            values (:user, :name, :mail, :active, :chg_at)
            on conflict (researchercode) do nothing
            """,
            {
                "user": new_id,
                "name": normalized_name or old_user.label or new_id,
                "mail": normalized_mail or old_user.addr or "",
                "active": bool(old_user.active),
                "chg_at": datetime.datetime.utcnow(),
            },
        )
        target = model.User.query.get(new_id)
        if target is None:
            raise RuntimeError(f"Failed to create migration target user {new_id}")

    _rekey_user_foreign_keys(old_id, new_id)

    stale = model.User.query.get(old_id)
    if stale is not None and stale.id != new_id:
        try:
            with model.db.session.begin_nested():
                model.db.session.delete(stale)
                model.db.session.flush()
        except IntegrityError:
            stale.addr = ""
            model.db.session.add(stale)

    target = model.User.query.get(new_id)
    if target is None:
        raise RuntimeError(f"Failed to load migrated user id {new_id}")
    return _sync_user_profile(target, normalized_mail, normalized_name)


def upsert_user(
    user: str, mail: str, name: str, *, migrate_to_requested_id: bool = False
) -> model.User:
    normalized_mail = (mail or "").strip().lower()
    normalized_name = (name or "").strip()
    requested_id = _normalize_user_id(user)
    if not requested_id:
        requested_id = scoped_user_id_from_identifier(normalized_mail)

    # Email is authoritative when present. Reuse any existing record for it.
    if normalized_mail:
        existing_by_mail = model.User.query.filter(
            func.lower(model.User.addr) == normalized_mail
        ).first()
        if existing_by_mail is not None:
            if migrate_to_requested_id and existing_by_mail.id != requested_id:
                return _migrate_user_identity(
                    existing_by_mail, requested_id, normalized_mail, normalized_name
                )
            return _sync_user_profile(
                existing_by_mail, normalized_mail, normalized_name
            )

    resolved_id = requested_id
    existing_by_id = model.User.query.get(resolved_id)
    if (
        existing_by_id is not None
        and normalized_mail
        and existing_by_id.addr
        and existing_by_id.addr.strip().lower() != normalized_mail
    ):
        # Existing id belongs to another email; derive a stable scoped id.
        resolved_id = scoped_user_id_from_identifier(normalized_mail)
        existing_by_id = model.User.query.get(resolved_id)

    if existing_by_id is None:
        model.db.session.execute(
            """
            insert into tlkpresearcher(researchercode, name, email, active, chg_at)
            values (:user, :name, :mail, :active, :chg_at)
            on conflict (researchercode) do nothing
            """,
            {
                "user": resolved_id,
                "name": normalized_name or resolved_id,
                "mail": normalized_mail,
                "active": True,
                "chg_at": datetime.datetime.utcnow(),
            },
        )
        existing_by_id = model.User.query.get(resolved_id)

    if existing_by_id is None:
        raise RuntimeError(f"Failed to upsert user record for {resolved_id}")

    return _sync_user_profile(existing_by_id, normalized_mail, normalized_name)


def is_admin(user: Any) -> bool:
    if not _user_is_active(user):
        return False
    return "admin" in get_memberships(user)


def get_memberships(user: Any) -> List[str]:
    user_id = _user_id_from_value(user)
    if user_id == "":
        return []
    if not _user_is_active(user):
        return []

    has_request_context = True
    try:
        request_cache = getattr(g, "_cached_memberships", None)
        request_cache_user_id = str(
            getattr(g, "_cached_memberships_user_id", "") or ""
        ).strip()
        if request_cache is not None and request_cache_user_id == user_id:
            return list(request_cache)
    except RuntimeError:
        has_request_context = False

    cache = _request_cache_dict("_cached_memberships_by_user")
    if cache is not None:
        cached = cache.get(user_id)
        if cached is not None:
            return list(cached)

    q = model.Membership.query
    q = q.filter(model.Membership.user == user_id)
    # inactive users are effectively not in any group
    q = q.filter(model.Membership.user_active)
    q = q.filter(model.Membership.group_active)
    q = q.filter(model.Membership.approved)
    ms = q.order_by(model.Membership.group).all()
    memberships = [m.group for m in ms]

    # Keep the request-scoped cache populated so app-level helpers and downstream
    # callers can reuse the same memberships list.
    if has_request_context:
        setattr(g, "_cached_memberships", memberships)
        setattr(g, "_cached_memberships_user_id", user_id)
    if cache is not None:
        cache[user_id] = memberships

    return memberships


def get_group(which: str) -> Optional[model.Group]:
    return model.Group.query.get(which)


def pi_of_group(group: str) -> str:
    M = model.Membership
    m = M.query.filter(M.group == group).filter(M.pi).first()
    return m.user


def change_pi_of_group(group: model.Group, user: model.User) -> None:
    m = model.PrimaryGroupMember
    m.query.filter(m.group == group.id).delete()
    new = m(group=group.id, user=user.id)
    model.db.session.add(new)


def get_all_groups_with_members(active: bool) -> List[model.Group]:
    q = model.Group.query
    q = q.filter(model.Group.active == active)
    q = q.filter(model.Group.has_membership)
    return q.order_by(model.Group.label).all()


def get_groups(which: List[str]) -> List[model.Group]:
    # sqlalchemy metaclass has confused mypy but it's fine so we ignore
    id_col = cast(Any, model.Group.id)
    q = model.Group.query
    q = q.filter(model.Group.active)
    q = q.filter(id_col.in_(which))
    return q.order_by(model.Group.label).all()


def get_members_of_group(
    group: model.Group, all: bool = False
) -> List[Tuple[str, bool, bool]]:
    q = model.Membership.query
    q = q.filter(model.Membership.group == group.id)
    q = q.filter(model.Membership.user_active)
    if not all:
        q = q.filter(model.Membership.approved)
    return [(r.user, r.pi, r.approved) for r in q.all()]


def remove_user_from_group(user: model.User, group: model.Group) -> None:
    req = model.GroupMember.query.get((group.id, user.id))
    if req is None:
        return  # not a member of group
    model.db.session.delete(req)


Group_leader_kind = Set[Literal["group_pi", "dev_pi", "admin"]]


def get_group_leader_kind(user: model.User, group: model.Group) -> Group_leader_kind:
    M = model.Membership
    q = M.query
    q = q.filter(M.user == user.id)
    q = q.filter(M.user_active)
    q = q.filter(M.approved)
    q = q.filter(
        or_(
            and_(M.group == group.id, M.pi),  # pi of current group
            and_(M.group == "DEV", M.pi),  # pi of DEV group
            M.group == "admin",  # any admin
        )
    )
    result: Group_leader_kind = set()
    for r in q.all():
        if r.group == group.id and r.pi:
            result.add("group_pi")
        elif r.group == "DEV" and r.pi:
            result.add("dev_pi")
        elif r.group == "admin":
            result.add("admin")
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
    # pi is only used on the creation form
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
            # only admins can change these
            del self.inst
            del self.active
        elif special:
            # not even admin can deactivate special groups
            del self.active
        if not create:
            # only use these on creation form
            del self.pi
            del self.id
        if special:
            # color does not apply to special groups
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
            elif c == "valid_color":  # this should never happen
                self.color.errors.append("invalid color sent by browser")
            elif c == "inst_fkey":
                self.inst.errors.append("invalid institute selected")


def get_institutes_datalist() -> Datalist:
    return list(_cached_institutes_datalist())


@lru_cache(maxsize=1)
def _cached_institutes_datalist() -> Tuple[Tuple[str, str], ...]:
    m = model.Inst
    q = m.query.filter(m.active)
    r = []
    for i in q.all():
        lbl = i.label
        if lbl != i.id:
            # if the label and id are distinct append the id to the end of the label
            # to make it easier for code and users to disambiguate similar labels
            lbl = f"{i.label} ({i.id})"
        r.append((i.id, lbl))
    return tuple(r)


def update_group(is_admin: bool, group: model.Group, form: GroupEditForm) -> bool:
    group.label = form.label.data
    group.description = form.description.data
    group.addr = form.addr.data
    group.link = form.link.data
    if form.color:  # not present on special groups
        group.color = form.color.data
    if is_admin:
        if form.inst:  # not present on special groups
            group.inst = form.inst.data
            if group.inst == "":
                group.inst = None
        if form.active:  # not present on special groups
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
    # make sure pi is valid before we do anything
    u = get_user(form.pi.data)
    if u is None:
        form.pi.errors.append("user not found")
        return False
    if not u.active:
        form.pi.errors.append("only active user may be PI")
        return False

    # create new group
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

    # add u as member of new group and mark as pi
    j = model.GroupMember(user=u.id, group=group.id, approved=func.now())
    model.db.session.add(j)
    pi = model.PrimaryGroupMember(user=u.id, group=group.id)
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
        if any(pi == m[0] for m in self.members):
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
    u = get_user(form.pi.data)
    if u is None:
        return None

    change_pi_of_group(group, u)
    try:
        model.db.session.commit()
    except IntegrityError as ex:
        model.db.session.rollback()
        form.set_errors_from_exception(ex)
        return None
    return u


def get_device(id: str) -> Optional[model.Device]:
    return model.Device.query.get(id)


def get_devices(active: bool) -> List[model.Device]:
    return (
        model.Device.query.filter(model.Device.active == active)
        .order_by(model.Device.label)
        .all()
    )


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
        """doa = dev pi or admin"""
        return self.dev_pi or self.admin

    @property
    def edit(self) -> bool:
        """edit = normal editing capabilities"""
        return self._edit or self.edit_any

    @property
    def edit_any(self) -> bool:
        """edit_any includes regular editing as well as special editing permissions"""
        return self._slot or self.doa

    @property
    def template(self) -> bool:
        # TODO: templates flag in DB/UI is currently not what gates template access
        return self._slot or self.doa

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
        # read only access
        perms = DevicePerms(False, False, False, None)
        if cache is not None and key is not None:
            cache[key] = perms
        return perms

    # is user an admin or the DEV PI
    is_admin, is_dpi = False, False
    M = model.Membership
    q = M.query
    q = q.filter(M.user == user.id)
    q = q.filter(M.user_active)
    q = q.filter(M.approved)
    q = q.filter(
        or_(
            and_(M.group == "DEV", M.pi),  # pi of DEV group
            M.group == "admin",  # any admin
        )
    )
    for r in q.all():
        if r.group == "DEV" and r.pi:
            is_dpi = True
        elif r.group == "admin":
            is_admin = True

    if is_admin or is_dpi:
        # we don't need any further information, even if it exists, since we can do everything now
        perms = DevicePerms(is_admin, is_dpi, True, None)
        if cache is not None and key is not None:
            cache[key] = perms
        return perms

    # see if we have regular edit access
    q = model.db.session.execute(
        """
            select count(G.deptcode) from devicegroup G where scannercode = :device and exists (
                select * from membership M where M."user" = :user and M.approved and M."group" = G.deptcode
            )
        """,
        {
            "user": user.id,
            "device": device.id,
        },
    )
    # member of at least one department associated with this device
    can_edit = q.first()[0] > 0

    # grab any special permissions on this device
    UD = model.UserDevice.query.get((user.id, device.id))
    perms = DevicePerms(False, False, can_edit, UD)
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
    q = model.db.session.execute(
        """
        select G.deptcode, G.dept_short from tlkpdept G
        inner join devicegroup DG using(deptcode)
        where G.department and G.iscurrent and DG.scannercode = :device
        order by 1
        """,
        {"device": device.id},
    )
    out = []
    for id, lbl in q.fetchall():
        if id != lbl:
            lbl += f" ({id})"
        out.append((id, lbl))
    return out


def groups_not_of_device(device: model.Device) -> Datalist:
    q = model.db.session.execute(
        """
        select G.deptcode, G.dept_short from tlkpdept G
        where G.department and G.iscurrent and not exists (
            select * from devicegroup DG where DG.deptcode = G.deptcode and DG.scannercode = :device
        ) order by 1
        """,
        {"device": device.id},
    )
    out = []
    for id, lbl in q.fetchall():
        if id != lbl:
            lbl += f" ({id})"
        out.append((id, lbl))
    return out


def add_group_to_device(group: str, device: str):
    dg = model.DeviceGroup(group=group, device=device)
    model.db.session.add(dg)


def remove_group_from_device(group: str, device: str):
    dg = model.DeviceGroup.query.get((device, group))
    if dg is None:
        # pairing does not exist so request
        # for pairing to not exit has succeeded
        return
    model.db.session.delete(dg)


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
        if any(dept.data == d for d in self.departments):
            raise validators.ValidationError("invalid department selected")

    def set_errors_from_exception(self, ex: IntegrityError) -> None:
        prefix, c = constraint_of(ex)
        if prefix == "groupdevice" and c == "deptcode_fkey":
            self.inactive.dept.errors.append("invalid department")


def process_add_group_to_device_form(dev: str, form) -> bool:
    dept = form.dept.data
    add_group_to_device(dept, dev)
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
    # get all dev group users and whether they have special permissions on this device
    q = model.db.session.execute(
        """
        select M."user", D.scannercode from membership M
        left join userdevice D on D.researchercode = M."user" and M."group" = 'DEV'
        where M."group" = 'DEV' and M.approved and M.user_active and D.scannercode is null or D.scannercode = :device
        order by 1
        """,
        {"device": device.id},
    )
    # bucket results and return
    active, inactive = [], []
    for user, dev in q.fetchall():
        if dev == device.id:
            active.append(user)
        else:
            inactive.append(user)

    return active, inactive


def get_dev_tech_status(user: model.User) -> Tuple[bool, bool]:
    if not user.active:
        return False, False

    # always returns a pair of numbers each of which is 0 or 1
    q = model.db.session.execute(
        """
        select count(M."user"), count(T.researchercode) from membership M
        left join technologist T on M."user" = T.researchercode and T.approved_on is not null
        where M."group" = 'DEV' and M.approved and M.user_active and M."user" = :user
        """,
        {"user": user.id},
    )
    dev, tech = q.first()
    is_dev = bool(dev)
    return is_dev, is_dev and bool(tech)


def is_technologist(user_id: str) -> bool:
    row = model.Technologist.query.get(user_id)
    return row is not None and row.approved_on is not None


def get_user_device_special_perms(
    user: model.User, device: model.Device
) -> Tuple[bool, model.UserDevice]:
    ud = model.UserDevice.query.get((user.id, device.id))
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
            # state of options don't matter if we're removing the entry
            return True

        checked = any(
            (self.templates.data, self.slot.data, self.medical.data, self.training.data)
        )
        if checked:
            return True
        # none of the static options have been checked,
        # see if the conditional option has been
        if self.tech and self.tech.data:
            return True

        # otherwise no options have been checked
        self.form_errors.append("at least one permission must be assigned")
        return False

    def populate(self, ud: model.UserDevice):
        self.populate_obj(ud)
        if not self.tech:
            ud.tech = False
