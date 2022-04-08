import datetime
import re
import secrets
from collections import defaultdict
from typing import (
    Any,
    DefaultDict,
    Dict,
    FrozenSet,
    Generator,
    List,
    Literal,
    NamedTuple,
    Optional,
    Set,
    Tuple,
    cast,
)

import itsdangerous
from flask import current_app
from flask.helpers import url_for
from flask_wtf import FlaskForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.expression import and_, or_
from sqlalchemy.sql.functions import func
from wtforms import Form, fields, validators, widgets

import message
import model


def constraint_of(ex: IntegrityError) -> Tuple[str, str]:
    prefix, name = ex.orig.diag.constraint_name.split("_", maxsplit=1)
    return (prefix, name)


def sign_message(msg: List[str]) -> str:
    signer = current_app.config["URL_SIGNER"]
    return signer.dumps(msg)


def read_signed_message(signature: str) -> Optional[List[str]]:
    signer = current_app.config["URL_SIGNER"]
    try:
        result = signer.loads(signature)
        # if we somehow got ill-typed data, consider it a failure
        if not isinstance(result, list):
            return None
        for v in result:
            if not isinstance(v, str):
                return None
        return result
    except itsdangerous.exc.BadData:
        return None


def discard_user_titles(name: str) -> str:
    # user's name is followed by bracketed titles that can be discarded
    return re.sub(" [([].*$", "", name)


def normalize_name(name: str) -> str:
    if "," in name:
        last, first = [s.strip() for s in name.split(",", 1)]
        return f"{first} {last}"
    return name.strip()


def record_tech_join(user: model.User) -> None:
    r = model.Technologist(user=user.id)
    model.db.session.add(r)


def notify_dev_pi_of_tech_join_form(user: model.User) -> None:
    M = model.Membership
    m = M.query.filter(M.group == "DEV").filter(M.pi).first()
    u = get_user(m.user)
    current_app.logger.info(f"{user.id} submitted the technologist join form")
    if u is None:
        current_app.logger.warning("no DEV PI found")
        return
    if u.addr == "":
        current_app.logger.warning("could not find email address for dev pi")
        return

    message.send(
        u.addr,
        f"technologist join from submission from {user.id}",
        f"{user.id} submitted the technologist join form",
    )


Datalist = List[Tuple[str, str]]


def get_departments_for_join_form(user: model.User) -> Datalist:
    # get all active departments (and DEV group) that user is NOT a current or pending member of.
    q = model.db.session.execute(
        """
        select D.deptcode, D.dept from tlkpdept D
        where D.iscurrent and (D.department or D.deptcode = 'Dev') and deptcode not in (
            select M."group" from membership M where M."user" = :user
        ) order by 2;
    """,
        {"user": user.id},
    )
    out = []
    for id, label in q.fetchall():
        if label != id:
            label = f"{label} ({id})"
        out.append((id, label))
    return out


def get_mailing_list_form(**kwargs):
    # create the dynamic part of the form from the app settings
    class MailingListsSubform(Form):
        def all_checkboxes(self) -> Generator[Tuple[str, bool], None, None]:
            for elm in self:
                if elm.type == "BooleanField":
                    yield (elm.label.text, elm.data)

        def validate(self) -> bool:
            if not Form.validate(self):
                return False

            if not any(x[1] for x in self.all_checkboxes()):
                self.form_errors.append("At least one list must be selected")
                return False
            return True

    lists = current_app.config["nih_mailing_lists"].items()
    for n, (name, description) in enumerate(lists):
        setattr(
            MailingListsSubform,
            f"ml-{n}",
            fields.BooleanField(label=name, description=description),
        )

    # this rest of the form is static
    choices = (("sub", "subscribe"), ("unsub", "unsubscribe"))

    class MailingListForm(FlaskForm):
        addr = fields.EmailField(
            validators=[
                validators.InputRequired(message="an email address is required")
            ],
            label="email",
            description="the NIH email address used for this list (must end in nih.gov)",
            render_kw={
                "pattern": ".*[@.]nih.gov",
                "title": "an email address ending in nih.gov",
            },
        )
        name = fields.StringField(
            validators=[validators.InputRequired(message="Your name is required")],
            label="name",
            description="your full name",
        )
        # include the dynamically generated portion here
        lists = fields.FormField(MailingListsSubform, label="lists")
        action = fields.RadioField(label="action", choices=choices, default="sub")

        def validate_addr(self, addr) -> None:
            # browser should block illegal addrs like this but may as well double check
            if "," in addr.data:
                raise validators.ValidationError("only one email address allowed")
            if "@" not in addr.data:
                raise validators.ValidationError("email address must contain @")
            # only let nih.gov addresses through
            _, dom = addr.data.split("@", 1)
            if not dom.endswith("nih.gov"):
                raise validators.ValidationError("only nih.gov email addresses allowed")

    return MailingListForm(**kwargs)


def process_mailing_list_form_submissions(form):
    # get all lists that have been selected
    lists = [list[0] for list in form.lists.all_checkboxes() if list[1]]
    addr = form.addr.data
    name = normalize_name(form.name.data)
    sub = form.action.data == "sub"
    listserv = current_app.config["nih_listserv"]
    for list in lists:
        msg = format_mailing_list_message(sub, list, name)
        message.send(listserv, "Automated list change", msg, sender=addr)


def format_mailing_list_message(sub: bool, which_list: str, name: str) -> str:
    if sub:
        return f"subscribe {which_list} {name}"
    return f"signoff {which_list}"


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
    # return a row if user is in DEV unless they have already submitted the form
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
    return q.first() is not None


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


def notify_group_pi_of_join_form(user: model.User, group: str) -> None:
    g = model.Group.query.get(group)
    if g is None:
        raise Exception(
            f"{user.id} attempted to join group that does not exist: {group}"
        )

    current_app.logger.info(f"{user.id} has requested to join {group}")

    M = model.Membership
    m = M.query.filter(M.group == group).filter(M.pi).first()
    u = get_user(m.user)
    if u is None:
        current_app.logger.warning(f"no PI to notify for {user.id} joining {group}")
        return
    if u.addr == "":
        current_app.logger.warning(
            f"no address to notify PI {u.id} about {user.id} joining {group}"
        )
        return

    token = sign_message(["join-group", user.id, group])
    approve = url_for("join-group-approve", token=token)
    deny = url_for("join-group-deny", token=token)
    page = url_for("group_membership", the_group=group)
    message.send(
        u.addr,
        f"{user.id} has requested to join {group}",
        f"""
{user.id} has requested to join {group}

click to approve: {approve}

click to deny: {deny}

or go to {page} to manage all memberships for {group}.
        """.strip(),
    )


def get_join_request(
    user: model.User, group: model.Group
) -> Optional[model.GroupMember]:
    return model.GroupMember.query.get((group.id, user.id))


def handle_join_request(approved: bool, req: model.GroupMember) -> None:
    if not approved:
        model.db.session.delete(req)
        return

    req.approved = func.now()
    model.db.session.add(req)


def notify_user_of_join_request_outcome(
    approved: bool, user: model.User, group: str
) -> None:
    if "@" not in user.addr:
        # don't have an address to send the notification
        current_app.logger.info(
            f"could not notify {user.id} of group membership change due to lack of address on file"
        )
        return

    outcome = "denied"
    if approved:
        outcome = "approved"
    msg = f"your request to join {group} was {outcome}"
    message.send(user.addr, msg, msg)


def get_user(user: str) -> Optional[model.User]:
    return model.User.query.get(user)


def upsert_user(user: str, mail: str, name: str) -> model.User:
    # upsert the user to ensure the record exists
    model.db.session.execute(
        "insert into tlkpresearcher(researchercode) values (:user) on conflict do nothing",
        {
            "user": user,
        },
    )
    # load the user
    u = model.User.query.get(user)

    # if the mail and/or display name have changed, update them
    # as long as the new values are not empty.
    add = False
    if mail != "" and u.addr != mail:
        u.addr = mail
        add = True
    if name != "" and u.label != name:
        u.label = name
        add = True
    if add:
        model.db.session.add(u)

    return u


def is_admin(user: model.User) -> bool:
    q = model.Membership.query
    q = q.filter(model.Membership.user == user.id)
    q = q.filter(model.Membership.group == "admin")
    q = q.filter(model.Membership.user_active)
    q = q.filter(model.Membership.approved)
    return q.first() is not None


def create_reset_token_for(user: str) -> str:
    token = secrets.token_urlsafe(64)
    # delete any previous tokens for user
    model.ResetTokens.query.filter(model.ResetTokens.for_user == user).delete()
    t = model.ResetTokens(token=token, for_user=user)
    # this can technically fail if we happen to generate the same token twice
    # but the odds against that are so great that it would actually be cool
    # if it happened
    model.db.session.add(t)
    # this is only expected to be called from cli so save it now
    # let any fk errors bubble up
    model.db.session.commit()
    return token


def get_user_from_token(token: str) -> Optional[model.User]:
    # delete all old tokens before we check
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    model.ResetTokens.query.filter(model.ResetTokens.issued < yesterday).delete()
    # see if the token exists
    rt = model.ResetTokens.query.get(token)
    if rt is None:
        return None
    # if it does grab the user and delete the token
    user = rt.user
    model.db.session.delete(rt)
    model.db.session.commit()
    return user


def get_memberships(user: model.User) -> List[str]:
    q = model.Membership.query
    q = q.filter(model.Membership.user == user.id)
    # inactive users are effectively not in any group
    q = q.filter(model.Membership.user_active)
    q = q.filter(model.Membership.group_active)
    q = q.filter(model.Membership.approved)
    ms = q.order_by(model.Membership.group).all()
    return [m.group for m in ms]


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
    return r


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
    return True


def get_group_membership_form(group: model.Group, active, pending):
    class ActiveMemberForm(Form):
        remove = fields.SubmitField(
            label="remove",
            render_kw={
                "data_confirm_title": "remove member",
                "data_confirm_confirm": "Remove",
            },
        )

    class ActiveMembersForm(Form):
        pass

    for m in active:
        setattr(
            ActiveMembersForm,
            f"member-{m}",
            fields.FormField(ActiveMemberForm, label=m),
        )

    class PendingMemberForm(Form):
        approve = fields.SubmitField(
            label="approve",
            render_kw={
                "data_confirm_title": "Approve membership",
                "data_confirm_confirm": "Approve",
            },
        )
        deny = fields.SubmitField(
            label="deny",
            render_kw={
                "data_confirm_title": "Deny membership",
                "data_confirm_confirm": "Deny",
            },
        )

    class PendingMembersForm(Form):
        pass

    for m in pending:
        setattr(
            PendingMembersForm,
            f"member-{m}",
            fields.FormField(PendingMemberForm, label=m),
        )

    class MembershipForm(FlaskForm):
        members = fields.FormField(ActiveMembersForm, label="active members")
        pending = fields.FormField(PendingMembersForm, label="pending members")

        def action(self):
            # only one action is possible at a time so grab the first hit and bail
            if self.members:
                for m in self.members:
                    if m.remove.data:
                        return "rm", m.label.text

            if self.pending:
                for m in self.pending:
                    if m.approve.data:
                        return "approve", m.label.text
                    if m.deny.data:
                        return "deny", m.label.text

            return "none", ""  # form was not submitted yet

    form = MembershipForm()
    if len(active) == 0:
        del form.members
    if len(pending) == 0:
        del form.pending

    return form


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
    if not user.active:
        # read only access
        return DevicePerms(False, False, False, None)

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
        return DevicePerms(is_admin, is_dpi, True, None)

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

    return DevicePerms(False, False, can_edit, UD)


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


def get_device_groups_form(related: Datalist):
    class ActiveGroupForm(Form):
        remove = fields.SubmitField(
            label="remove",
            render_kw={
                "data_confirm_title": "remove department",
                "data_confirm_confirm": "remove",
            },
        )

    class DeviceForm(FlaskForm):
        def which(self):
            for elm in self:
                if elm.remove.data:
                    return elm.name

    for id, label in related:
        setattr(DeviceForm, id, fields.FormField(ActiveGroupForm, label=label))

    return DeviceForm()


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
        left join technologist T on M."user" = T.researchercode and M."group" = 'DEV'
        where M."group" = 'DEV' and M.approved and M.user_active and M."user" = :user
        """,
        {"user": user.id},
    )
    dev, tech = q.first()
    is_dev = bool(dev)
    return is_dev, is_dev and bool(tech)


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

    def validate(self) -> bool:
        if not FlaskForm.validate(self):
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


def get_template(
    for_device: model.Device, template_id: str
) -> Optional[model.Template]:
    return model.Template.query.get((template_id, for_device.id))


def templates_of_device(
    device: model.Device, archived: bool = False
) -> List[model.Template]:
    M = model.Template
    q = (
        M.query.filter(M.device == device.id)
        .filter(M.hidden == archived)
        .order_by(M.label)
    )
    return q.all()


def all_templates_of_device(device: model.Device) -> Datalist:
    M = model.Template
    q = M.query.filter(M.device == device.id).order_by(M.hidden, M.label)
    out = []
    for t in q.all():
        archived = ""
        if t.hidden:
            archived = " [archived]"
        out.append((t.id, f"{t.label} ({t.id}){archived}"))
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
        if not any(clone.data == id for (id, _) in self.templates):
            raise validators.ValidationError("invalid template")

    def set_errors_from_exception(self, ex: IntegrityError) -> None:
        prefix, c = constraint_of(ex)
        if prefix != "tbltemplates":
            return
        if c == "pkey":
            self.id.errors.append(
                "this id is already in use by another template on this device"
            )
        elif c == "scannercode_fkey":
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
    model.db.session.flush()  # need tmpl inserted for next step

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
    M = model.TemplateEntry
    q = M.query
    q = q.filter(M.device == device.id)
    q = q.filter(M.template == template.id)
    q = q.order_by(M.hour, M.dow)
    return q.all()


def get_start_day_of(device: model.Device) -> Optional[datetime.date]:
    M = model.ScheduleEntry
    d = model.db.session.query(func.max(M.date)).filter(M.device == device.id).scalar()
    if d is not None:
        d += datetime.timedelta(days=1)
    return d


def next_sunday() -> datetime.date:
    d = datetime.date.today()
    w = d.isoweekday()
    # subtract w days from date, taking it back to the last sunday,
    # and then add 1 week taking it to the next sunday
    # if this is sunday, there is no change
    d += datetime.timedelta(days=-w, weeks=1)
    return d


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
    """
    uniq takes a string and returns a list of strings
    of the unique elements in the same order as xs
    """
    acc = []
    seen = set()
    for x in xs:
        if x not in seen:
            seen.add(x)
            acc.append(x)
    return acc


def validate_templates_before_application(device: model.Device, templates: str):
    ts = uniq(templates)
    errs = []

    if len(ts) == 0:
        errs.append("no templates to apply")
        return errs

    # quick sanity check that all the templates exist in a legal state
    MT = model.Template
    id_col = cast(Any, MT.id)  # mypy confused by sqlalchemy
    q = (
        MT.query.filter(MT.device == device.id)
        .filter(id_col.in_(ts))
        .filter(MT.hidden == False)
    )
    n = q.count()
    if n != len(ts):
        # the form validates this in the same transaction so this should never happen
        # we report out of an abundance of caution but do not spend time on the error message
        errs.append("invalid template codes provided")
        if n == 0:
            return errs

    # load all the cells of all the templates to check that they're valid
    has_invalid: Set[str] = set()
    cell_count: DefaultDict[str, int] = defaultdict(int)

    MI = model.Inst
    q = MI.query.filter(MI.active)
    inst: Set[Optional[str]] = set(i.id for i in q.all())
    inst.add(None)  # in all these sets we include "" to simplify checks

    # after construction, a (group, member) pair is valid if
    # - group is in groups
    # - member is in groups[group]
    groups: Dict[Optional[str], Set[Optional[str]]] = {
        None: {None}
    }  # no group only allows no member
    member_dls = all_member_datalists_by_group(device)
    support_dls = support_request_datalists(device)
    for g, ms in member_dls.items():
        s: Set[Optional[str]] = set(m for (m, _) in ms)
        s.add(None)  # so not being set is valid
        groups[g] = s
    # special case for training
    groups["training"] = set(m for (m, _) in support_dls.training)
    groups["training"].add(None)

    M = model.TemplateEntry
    template_col = cast(Any, M.template)
    q = M.query.filter(M.device == device.id).filter(template_col.in_(ts))

    for cell in q.all():
        t = cell.template
        cell_count[t] += 1
        if cell.inst not in inst:
            has_invalid.add(t)
        elif not (cell.group in groups and cell.user in groups[cell.group]):
            has_invalid.add(t)

    # this is definitely something that should NEVER happen
    # but if it somehow does we stop it before the error
    # spreads to the rest of the system
    for k, v in sorted(cell_count.items(), key=lambda p: p[0]):
        if v != 7 * 24:
            errs.append(f"{k} malformed: has {v} entries instead of {7*24}")

    for x in sorted(has_invalid):
        errs.append(f"{x} has invalid entries")

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


def schedule_for(
    device: model.Device, start: datetime.date, end: datetime.date
) -> List[model.ScheduleEntry]:
    M = model.ScheduleEntry
    q = M.query.filter(M.device == device.id)
    q = q.filter(M.date.between(start, end))
    q = q.order_by(M.hour, M.date)
    return q.all()


def group_schedule_entries(
    entries: List[model.ScheduleEntry],
) -> Tuple[List[str], List[List[model.ScheduleEntry]]]:
    days = set()
    hdr = []
    out: List[List[model.ScheduleEntry]] = []
    for _ in range(24):
        out.append([])
    for entry in entries:
        if entry.date not in days:
            days.add(entry.date)
            hdr.append(fmt_date(entry.date))
        out[entry.hour].append(entry)
    return hdr, out


def group_template_entries(
    entries: List[model.TemplateEntry],
) -> List[List[model.TemplateEntry]]:
    out: List[List[model.TemplateEntry]] = []
    for _ in range(24):
        out.append([])
    for entry in entries:
        out[entry.hour].append(entry)
    return out


def device_schedule_extreme_dates(
    device: model.Device,
) -> Tuple[Optional[datetime.date], Optional[datetime.date]]:
    """return the first and last scheduled day for device
    or (None, None) for a device that has never had entries scheduled"""
    M = model.ScheduleEntry
    return (
        model.db.session.query(func.min(M.date), func.max(M.date))
        .filter(M.device == device.id)
        .first()
    )


def date_or_today(date: Optional[datetime.date]) -> datetime.date:
    if date is None:
        return datetime.date.today()
    return date


def fmt_date(date: Optional[datetime.date]) -> str:
    if date is None:
        return ""
    return date.strftime("%Y-%m-%d")


def parse_date(s: str) -> Optional[datetime.date]:
    """parses a string in YYYY-MM-DD format, returning None on failure"""
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_days(days: str) -> Optional[int]:
    """parses a reasonable number of days (1-31) or returns None"""
    try:
        n = int(days)
        if not (0 < n < 32):
            return None
        return n
    except ValueError:
        return None


def end_date(date: datetime.date, days: int) -> datetime.date:
    return date + datetime.timedelta(days=days)


def user_datalist_entry(id: str, name: str) -> str:
    if name == "" or id == name:
        return id
    return f"{name} ({id})"


def get_device_from_schedid(eid) -> Optional[model.Device]:
    M = model.ScheduleEntry
    entry = M.query.filter(M.id == eid).first()
    if entry is None:
        return None
    return get_device(entry.device)


def get_sched_log_entry(eid: int):
    r = model.SchedLogEntry.query.get(eid)

    if r is None:
        return None

    return r.entries


class SupportRequestDatalists(NamedTuple):
    tech: Datalist
    medical: Datalist
    training: Datalist


def support_request_datalists(device: model.Device) -> SupportRequestDatalists:
    q = model.db.session.execute(
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
    for id, name, is_tech, is_med, is_train in q.fetchall():
        p = (id, user_datalist_entry(id, name))
        if is_tech:
            tech.append(p)
        if is_med:
            med.append(p)
        if is_train:
            train.append(p)

    return SupportRequestDatalists(tech, med, train)


def all_member_datalists_by_group(device: model.Device) -> Dict[str, Datalist]:
    """for each department of device get a datalist of its members"""
    q = model.db.session.execute(
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
    for dept, id, name in q.fetchall():
        p = (id, user_datalist_entry(id, name))
        datalists[dept].append(p)
    return datalists


def member_datalists_by_group_for(
    device: model.Device, user: model.User
) -> Dict[str, Datalist]:
    """for each department of device that user is a member of, get a datalist of its members"""
    q = model.db.session.execute(
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
    for dept, id, name in q.fetchall():
        p = (id, user_datalist_entry(id, name))
        datalists[dept].append(p)
    return datalists


def all_group_colors() -> Dict[str, str]:
    # it's okay if this grabs more than apply since it's only used internally
    # and an old entry may reference a group that's no longer valid
    q = model.db.session.execute(
        """
            select d.deptcode, d.color
            from tlkpdept d
        """,
    )
    out = {}
    for k, v in q.fetchall():
        out[k] = v
    return out


def all_groups_of_device(device: model.Device) -> Datalist:
    q = model.db.session.execute(
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
    for id, name in q.fetchall():
        if name != id:
            name = f"{name} ({id})"
        out.append((id, name))
    return out


def groups_of_device_for(device: model.Device, user: model.User) -> Datalist:
    q = model.db.session.execute(
        """
            with users_departments as (
                select d.deptcode
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
    for id, name in q.fetchall():
        if name != id:
            name = f"{name} ({id})"
        out.append((id, name))
    return out


def off_hours() -> Set[int]:
    """return set of standard off hours"""
    s = set(range(0, 8))
    s.add(22)
    s.add(23)
    return s


def _used(entry: model.ScheduleEntry) -> bool:
    if entry.user is not None:
        return True
    for g in (entry.group, entry.orig_group):
        if g is not None:
            # historical records that need to be treated as null
            if g not in ("", "DEV"):
                return True
    return False


def strike_used_off_hours(
    off_hours: Set[int], entries: List[model.ScheduleEntry]
) -> None:
    """remove any off_hours that are used by any entry in entries"""
    for entry in entries:
        # if there's a set entry in off_hours, that hour is no longer an off hour
        if entry.hour in off_hours and _used(entry):
            off_hours.remove(entry.hour)
            if len(off_hours) == 0:
                break


def group_off_hours_into_runs(off_hours: Set[int]) -> List[List[int]]:
    # sort off hours
    hours = list(sorted(off_hours))
    # add a sentinel to the end
    hours += [99]

    # walk over [(h[0], h[1]), (h[1], h[2]), ..., (h[n-1], h[n]), (h[n], 99)]
    # and split it into lists of consecutive hours, eg [[0], [2,3], [5,7], [9,9]]
    acc, cur = [], []
    for h, next in zip(hours, hours[1:]):
        cur.append(h)
        if next == 99:
            # at the end nothing more to do
            cur.sort()
            acc.append(cur)
            break
        if next - h != 1:
            # nonconsecutive entries, push cur and reset
            cur.sort()
            acc.append(cur)
            cur = []

    return acc


def convert_off_hour_runs_into_map(runs: List[List[int]]) -> Dict[int, List[int]]:
    out = {}
    for xs in runs:
        out[xs[0]] = xs
    return out


def fmt_hours() -> Dict[int, str]:
    out = {}
    for i in range(24):
        s = ""
        if i == 0:
            s = "Mid."
        elif i == 12:
            s = "Noon"
        else:
            m = "a"
            t = i
            if i > 12:
                t -= 12
                m = "p"
            s = f"{t}{m}m"
        out[i] = s
    return out


def db_now() -> Tuple[datetime.date, int, int]:
    "get current day, hour, and minute from transaction"
    q = model.db.session.execute(
        """
        select
            current_date,
            extract(hour from current_timestamp)::integer as hour,
            extract(minute from current_timestamp)::integer as minute
        """
    )
    return q.first()


class JsonForm(FlaskForm):
    """
    This form is used for javascript submit.
    There are other ways to handle this,
    but this is by far the simplest.
    """

    payload = fields.TextAreaField(validators=[validators.InputRequired()])


def verify_and_prep_template_diffs(
    diffs, entries, institutes, groups, members_of_groups
):
    # grab just the referenced entries
    ids = frozenset(int(d["id"]) for d in diffs)
    referenced = {e.id: e for e in entries if e.id in ids}

    # convert the datalists into sets for easier comparison
    inst = frozenset(id for (id, _) in institutes)
    g = frozenset(id for (id, _) in groups)
    # absence of a group has no members to simplify checks
    # for templates, neither ever has any members but are not
    # included in members_of_groups so we add them first
    m = {
        "": frozenset(),
        "maint": frozenset(),
        "training": frozenset(),
    }
    for k, v in members_of_groups.items():
        m[k] = frozenset(id for (id, _) in v)

    errors = defaultdict(list)
    staged = []

    def check(id, diff, key, entry_val, set):
        # input from the site uses "" for NULL so we normalize to that here
        # to simplify all the checks
        if entry_val is None:
            entry_val = ""
        if key not in diff:
            return entry_val, True
        old, new = diff[key]
        failed = False
        # if entry_val is empty we don't check
        # since the worst case it transitioned to empty
        # but if it is now empty and wasn't before
        # the new transition is still always legal
        # and cannot step on anyone else's toes as the slot
        # is up for grabs
        if entry_val != "" and entry_val != old:
            errors[id].append(
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
            if new not in set:
                errors[id].append(
                    {
                        "type": "removed",
                        "key": key,
                        "value": new,
                    }
                )
                failed = True
        return ret, not failed

    for diff in diffs:
        id = int(diff["id"])
        entry = referenced[id]
        check(id, diff, "institute", entry.inst, inst)
        group, ok = check(id, diff, "group", entry.group, g)
        # only check member if group check succeeded,
        # otherwise the check can be meaningless;
        # but the cell has already failed validation so it's okay
        if ok:
            check(id, diff, "member", entry.user, m[group])

        # validation passed, prepare the changes for this entry
        if id not in errors:
            # for each item in diff set the entry value to the new value,
            # but if the new value is "" set it to NULL
            if "institute" in diff:
                entry.inst = diff["institute"][1] or None
            if "group" in diff:
                entry.group = diff["group"][1] or None
            if "member" in diff:
                entry.user = diff["member"][1] or None
            staged.append(entry)

    # if there are errors, only return the errors
    # if there are no errors, only return the entries to commit
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
    # construct datetimes from the dates
    c = datetime.datetime(
        cur_date.year, cur_date.month, cur_date.day, cur_hour, cur_minute
    )
    e = datetime.datetime(
        entry_date.year, entry_date.month, entry_date.day, entry_hour, 0
    )
    if shift:
        # take 15 minutes off of the entry time so we can compare it directly to the current time
        # while taking the deadline into account
        e -= datetime.timedelta(minutes=15)
    return e < c


def null2epsilon(s: Optional[str]) -> str:
    if s is None:
        return ""
    return s


def verify_scheduler_diffs(
    diffs,
    entries: List[model.ScheduleEntry],
    perms: DevicePerms,
    support: SupportRequestDatalists,
    cur_date: datetime.date,
    cur_hour: int,
    cur_minute: int,
    groups: Datalist,
    members_of_groups: Dict[str, Datalist],
    user: model.User,
):
    # pair up the diffs and entries to ease further processing
    ids = frozenset(int(d["id"]) for d in diffs)
    referenced = {e.id: e for e in entries if e.id in ids}
    when = {}
    xs = []
    for diff in diffs:
        id = int(diff["id"])
        entry = referenced[id]
        xs.append((id, diff, entry))
        past = is_old(
            entry.date, entry.hour, cur_date, cur_hour, cur_minute, shift=False
        )
        when[id] = (past, entry.date, entry.hour)

    # set up some closures to reduce the error handling boilerplate
    errors: DefaultDict[int, List[Dict[str, str]]] = defaultdict(list)

    def fail(id: int, msg: Dict[str, str]) -> None:
        errors[id].append(msg)

    def fail_removed(id, key, value):
        fail(id, {"type": "removed", "key": key, "value": value})

    def fail_overwrote(id, key, expected, got):
        fail(
            id,
            {
                "type": "overwrote",
                "key": key,
                "expected": expected,
                "got": got,
            },
        )

    def fail_user_removed(id, key, value):
        fail(id, {"type": "user-removed", "key": key, "value": value})

    # in some stages we find errors so catastrophic that the entry needs to be yanked
    # from further processing or there will be second and third order errors.
    # we yank them by deleting their entry in referenced
    # then before the next stage we call this to filter out any entries we have removed
    def compact():
        if len(xs) != len(referenced):
            return [(id, diff, entry) for id, diff, entry in xs if id in referenced]
        return xs

    # first, check for submissions that missed the submission deadline
    if not perms.edit_any:
        for id, _, entry in xs:
            if is_old(entry.date, entry.hour, cur_date, cur_hour, cur_minute):
                fail(id, {"type": "expired"})
                # do no further validation for expired entries
                # as there is nothing a user who sees this message could do about anything else
                del referenced[id]
        # all entries expired, nothing more to do
        if len(referenced) == 0:
            return [], [], {}, errors

        xs = compact()

    g = frozenset(id for (id, _) in groups)

    # absence of a group has no members to simplify checks,
    # maint never has members
    # training is computed from support.training
    m: Dict[str, FrozenSet[str]] = {
        "": frozenset(),
        "maint": frozenset(),
        "training": frozenset(id for (id, _) in support.training),
    }
    for k, v in members_of_groups.items():
        m[k] = frozenset(id for (id, _) in v)

    # ensure group assignments are valid
    for id, diff, entry in xs:
        group = null2epsilon(entry.group)

        if "group" not in diff:
            # even though we're not updating the group, we need to make sure
            # that it's valid as all other checks below assume the group is valid
            if group != "" and group not in g:
                fail_removed(id, "group", group)
                del referenced[id]
            continue

        old, new = diff["group"]

        # check that no one overwrote the group
        # but skip if it's currently empty as that is a no harm no foul situation
        # as it is currently up for grabs by anyone
        if group != "" and group != old:
            fail_overwrote(id, "group", group, old)
            del referenced[id]
            continue

        # new group no longer on this device.
        # note that we do not check that the old group is valid here:
        # this implicitly treats a removed group the same as an empty group
        # but we're assuming that that frontend made the then-appropriate checks
        if new != "" and new not in g:
            fail_removed(id, "group", new)
            del referenced[id]
            continue

        if not perms.edit_any:
            # no longer member of old group
            if old != "" and user.id not in m[old]:
                fail_user_removed(id, "group", old)
                del referenced[id]

            # no longer member of new group
            if new != "" and user.id not in m[new]:
                fail_user_removed(id, "group", new)
                del referenced[id]

    xs = compact()

    # ensure member assignments are valid
    for id, diff, entry in xs:
        if "member" not in diff:
            continue

        old, new = diff["member"]

        member = null2epsilon(entry.user)
        if member != "" and old != member:
            fail_overwrote(id, "member", member, old)

        # make sure new still belongs to the group
        # we do not check that old still belongs to the group because
        #  - it's irrelevant to safety
        #  - we can assume that it was correct
        if new != "":
            # need the latest group to check membership against
            group = null2epsilon(entry.group)
            if "group" in diff:
                _, group = diff["group"]

            if new not in m[group]:
                fail_removed(id, "member", new)

    # split out support requests so we can verify them separately,
    # now that we know they can't be expired or have lost edit privilege.
    srs: List[model.SupportRequest] = []

    # get the support request of kind n or create a blank one
    def get_sr(entry, n):
        for sr in entry.requests:
            if sr.supportkind == n:
                return sr, False

        # no existing sr, create one
        # it will be filled in later
        sr = model.SupportRequest()
        sr.supportkind = n
        sr.filed_by = user.id
        entry.requests.append(sr)
        return sr, True

    support_human_name = {
        1: "medical",
        2: "training",
        3: "technologist",
    }

    support_staff = {
        1: frozenset(id for (id, _) in support.medical),
        2: frozenset(id for (id, _) in support.training),
        3: frozenset(id for (id, _) in support.tech),
    }

    def record_sr(id, diff, entry, k, n):
        if k not in diff:
            return
        srs.append(
            (
                id,
                support_human_name[n],
                diff[k],
                *get_sr(entry, n),
                user.id in support_staff[n] or perms.edit_any,
            )
        )

    for id, diff, entry in xs:
        record_sr(id, diff, entry, "med", 1)
        record_sr(id, diff, entry, "train", 2)
        record_sr(id, diff, entry, "tech", 3)

    def returns():
        # if there are errors, only return the errors
        if len(errors) > 0:
            return [], [], {}, errors
        return xs, srs, when, None

    # no support requests so we've verified everything
    if len(srs) == 0:
        return returns()

    for id, kind, diff, sr, is_new, _ in srs:
        if not is_new:
            # check overwrites.
            # the only ones we can detect are scan/cover and handler
            # we do not check scan/cover as every error self corrects:
            # that is if we change from scan to cover and there's an overwrite,
            # the result is the same
            if "handler" in diff:
                old, _ = diff["handler"]
                handler = null2epsilon(sr.fulfilled_by)
                if handler != "" and handler != old:
                    fail_overwrote(id, f"{kind} handler", handler, old)

        # the request was cancelled so we ignore any other changes
        if "requested" in diff and not diff["requested"]:
            continue

        # make sure the handler is valid
        if "handler" in diff:
            _, new = diff["handler"]
            if new != "" and new not in support_staff[sr.supportkind]:
                fail_removed(id, f"{kind} handler", new)

    return returns()


def apply_scheduler_diffs(user: model.User, xs):
    stage = []
    for _, diff, entry in xs:
        entry.modified_by = user.id
        if "group" in diff:
            entry.group = diff["group"][1] or None
        if "member" in diff:
            entry.user = diff["member"][1] or None
        stage.append(entry)
    return stage


def apply_scheduler_sr_diffs(user: model.User, srs):
    notes = []
    for id, kind, diff, sr, is_new, staff_request in srs:
        note = {"id": id, "kind": kind}
        sr.modified_by = user.id

        # set a default state that may be overridden by something more specific
        if is_new:
            note["state"] = "new"
        else:
            note["state"] = "updated"

        # this won't affect any state transitions, simply note it
        if "subkind" in diff:
            sr.note = diff["subkind"][1]
            note["subkind"] = diff["subkind"]

        canceled = False
        decision = sr.approved or False
        if "requested" in diff:
            if diff["requested"]:
                # if this is a new entry this does nothing;
                # if this is an old entry with approved=False,
                # this resets it to a new-ish request
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

        # as we null out the handler when the request is retracted/canceled
        # as otherwise anyone could take an unchecked SR with a set handler
        # and make it approved by re-checking the SR.
        # hence we can skip all this when the SR is canceled.
        if "handler" in diff and not canceled:
            old, new = diff["handler"]
            sr.fulfilled_by = new or None

            # if there's a handler in the new state, record it
            if new != "":
                note["handler"] = new

            if old == "" and new != "":
                sr.approved = True
                note["state"] = "approved"
            elif old != "" and new == "":
                # no longer assigned to anyone but request still open
                sr.approved = None
                note["state"] = "unassigned"
            else:
                # reassigned from one handler to another without altering approval state
                note["state"] = "reassigned"

        notes.append(note)
    return notes


def prepare_notifications(send_notifications, when, diffs, srs_notes):
    # filter out diffs that won't cause a notification
    diffs_out = []
    if not send_notifications:
        for d in diffs:
            id = int(d["id"])
            # old entry
            if when[id][0]:
                continue
            # only has SR
            if not any(x in d for x in ("group", "member")):
                continue
            diffs_out.append(d)

    srs_out = {
        "schedule": [],
        "training": [],
        "medical": [],
        "technologist": [],
    }
    for sn in srs_notes:
        t = when[sn["id"]]
        # old entry
        if t[0]:
            continue
        srs_out["schedule"].append(with_time)
        srs_out[sn["kind"]].append(with_time)

    return diffs_out, srs_out


def fmt_notifications(when, ens, sns):
    hours = fmt_hours()
    out = {
        "schedule": fmt_regular_notifications(hours, ens)
        + fmt_support_notifications(hours, when, sns["schedule"], True),
    }
    for k in ("training", "medical", "technologist"):
        out[k] = fmt_support_notifications(hours, when, sns[k], False)
    return out


def fmt_regular_notifications(hours, ens):
    if len(ens) == 0:
        return ""
    acc = []

    def push(t):
        acc.append(t)

    def push_state(what, old, new):
        if old == "":
            push(f"\tset {what} to {new}")
        elif new == "":
            push(f"\tcleared {what} (was {old})")
        else:
            push(f"\tchanged {what} from {old} to {new}")

    for en in ens:
        hour = hours[int(en["hour"])]
        push(f"{en['date']}: {hour}")
        if "group" in en:
            push_state("group", *en["group"])
        if "member" in en:
            push_state("member", *en["member"])

    return "\n".join(acc)


def fmt_support_notifications(hours, when, sns, include_kind):
    if len(sns) == 0:
        return ""
    return ""  # TODO


def send_scheduler_notifications(device: model.Device, msgs):
    tbl = (
        ("schedule", device.addr, "schedule change"),
        ("training", device.train_addr, "training request change"),
        ("medical", device.med_addr, "medical coverage request change"),
        ("technologist", device.tech_addr, "technologist request change"),
    )
    notes = []
    for key, addr, subj in tbl:
        msg = msgs[key]
        if msg == "":
            continue

        def note(what):
            notes.append({"key": key, "msg": what})

        if "@" not in addr:
            note("address")
            continue

        subject = f"[scheduler] {device.label}: {key} {subj}"
        ok = message.send(addr, subject, msg)
        note("failed" if not ok else "success")

    return notes
