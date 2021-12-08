import datetime
import re
import secrets
from typing import Any, Generator, List, Literal, Optional, Set, Tuple, cast

import itsdangerous
from flask import current_app
from flask.helpers import url_for
from flask_wtf import FlaskForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.expression import and_, or_
from sqlalchemy.sql.functions import func
from wtforms import fields, validators, widgets

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


def get_departments_for_join_form(user: model.User) -> List[Tuple[str, str]]:
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
    return q.fetchall()


def get_mailing_list_form(**kwargs):
    # create the dynamic part of the form from the app settings
    class MailingListsSubform(FlaskForm):
        def all_checkboxes(self) -> Generator[Tuple[str, bool], None, None]:
            for elm in self:
                if elm.type == "BooleanField":
                    yield (elm.label.text, elm.data)

        def validate(self) -> bool:
            if not FlaskForm.validate(self):
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
            description="the NIH email address used for this list",
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
        render_kw={"list": "departments", "autocomplete": "off"},
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
    return bool(q.first())


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
    return bool(q.first())


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
        render_kw={"autocomplete": "off"},
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
        render_kw={"list": "institutes", "autocomplete": "off"},
    )
    # pi is only used on the creation form
    pi = fields.StringField(
        label="pi",
        description="must be valid AD name of user in database",
        validators=[validators.InputRequired()],
        render_kw={"autocomplete": "off"},
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


def get_institutes_for_group_edit_form() -> List[Tuple[str, str]]:
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


def get_group_membership_form(group: model.Group, membership_data):
    pi = None
    active = []
    pending = []
    for m, is_pi, is_active in membership_data:
        if is_pi and is_active:
            pi = m
        elif is_active:
            active.append(m)
        else:
            pending.append(m)
    active.sort()
    pending.sort()

    choices = active
    if pi is not None:
        choices = [pi] + active

    class PrimarySubForm(FlaskForm):
        members = fields.SelectField(label="members", choices=choices, default=pi)
        submit = fields.SubmitField(label="change")

    class ActiveMemberForm(FlaskForm):
        remove = fields.SubmitField(label="remove")

    class ActiveMembersForm(FlaskForm):
        pass

    for m in active:
        setattr(
            ActiveMembersForm,
            f"member-{m}",
            fields.FormField(ActiveMemberForm, label=m),
        )

    class PendingMemberForm(FlaskForm):
        approve = fields.SubmitField(label="approve")
        deny = fields.SubmitField(label="deny")

    class PendingMembersForm(FlaskForm):
        pass

    for m in pending:
        setattr(
            PendingMembersForm,
            f"member-{m}",
            fields.FormField(PendingMemberForm, label=m),
        )

    class MembershipForm(FlaskForm):
        pi = fields.FormField(PrimarySubForm, label="change primary investigator")
        members = fields.FormField(ActiveMembersForm, label="active members")
        pending = fields.FormField(PendingMembersForm, label="pending members")

        def action(self):
            # only one action is possible at a time so grab the first hit and bail
            if self.pi and self.pi.submit.data:
                return "pi", self.pi.members.data

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
        del form.pi  # can't change pi if no other options
        del form.members
    if len(pending) == 0:
        del form.pending

    return form


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
    can_edit = q.first() > 0

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
        render_kw={"autocomplete": "off"},
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
                self.id.errors("this id is already in use by another device")
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


def groups_of_device(device: model.Device) -> Tuple[List[str], List[str]]:
    # get all active departments and whether they're associated with device
    q = model.db.session.execute(
        """
        select G.deptcode, D.scannercode from tlkpdept G left join devicegroup D using(deptcode)
        where G.department and G.iscurrent and D.scannercode is null or D.scannercode = :device
        order by 1
        """,
        {"device": device.id},
    )
    # bucket results and return
    related, unrelated = [], []
    for dept, dev in q.fetchall():
        if dev == device.id:
            related.append(dept)
        else:
            unrelated.append(dept)
    return related, unrelated


def get_device_groups_form(related: List[str], unrelated: List[str]):
    class ActiveGroupForm(FlaskForm):
        remove = fields.SubmitField(label="remove")

    class ActiveGroupsForm(FlaskForm):
        pass

    for g in related:
        setattr(
            ActiveGroupsForm, f"group-{g}", fields.FormField(ActiveGroupForm, label=g)
        )

    class InactiveGroupForm(FlaskForm):
        dept = fields.StringField(
            label="department", render_kw={"list": "departments", "autocomplete": "off"}
        )
        add = fields.SubmitField(label="add")

        def validate(self) -> bool:
            if not FlaskForm.validate(self):
                return False
            if self.add.data and self.dept.data == "":
                self.dept.errors.append("must select department to add")
                return False
            return True

    class Form(FlaskForm):
        active = fields.FormField(ActiveGroupsForm, label="assigned departments")
        inactive = fields.FormField(InactiveGroupForm, label="add department")

        def __init__(self, departments, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # datalist builder expects each entry to be in (key, value) format
            self.departments = zip(departments, departments)

        def action(self):
            if self.inactive:
                if self.inactive.add.data:
                    return "add", self.inactive.dept.data
            if self.active:
                for d in self.active:
                    if d.remove.data:
                        return "rm", d.label.text
            return "", ""

        def set_errors_from_exception(self, ex: IntegrityError) -> None:
            prefix, c = constraint_of(ex)
            if prefix == "groupdevice" and c == "deptcode_fkey":
                self.inactive.dept.errors.append("invalid department")

    form = Form(unrelated)
    if len(related) == 0:
        del form.active
    if len(unrelated) == 0:
        del form.inactive

    return form


def process_device_groups_form(dev: str, form) -> Literal["okay", "fatal", "invalid"]:
    act, dept = form.action()
    if act == "add":
        add_group_to_device(dept, dev)
    elif act == "rm":
        remove_group_from_device(dept, dev)
    else:
        return "fatal"
    try:
        model.db.session.commit()
    except IntegrityError as ex:
        # can only fire if adding a pairing that already exists
        # but that means the request is already fulfilled
        # so we ignore the error
        form.set_errors_from_exception(ex)
        model.db.session.rollback()
        return "invalid"
    return "okay"


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

    rm = fields.SubmitField(label="remove from device")
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
