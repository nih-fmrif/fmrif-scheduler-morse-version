import datetime
import re
import secrets
from typing import Any, Generator, List, Literal, Optional, Set, Tuple, cast

import itsdangerous
from flask import current_app
from flask_mail import Message
from flask_wtf import FlaskForm
from sqlalchemy.sql.expression import and_, or_
from wtforms import fields, validators

import message
import model


def discard_user_titles(name: str) -> str:
    # user's name is followed by bracketed titles that can be discarded
    return re.sub(" [([].*$", "", name)


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


def get_user(user: str) -> Optional[model.User]:
    return model.User.query.get(user)


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


def normalize_name(name: str) -> str:
    if "," in name:
        last, first = [s.strip() for s in name.split(",", 1)]
        return f"{first} {last}"
    return name.strip()


def format_mailing_list_message(sub: bool, which_list: str, name: str) -> str:
    if sub:
        return f"subscribe {which_list} {name}"
    return f"signoff {which_list}"


def get_devices(active: bool) -> List[model.Device]:
    return (
        model.Device.query.filter(model.Device.active == active)
        .order_by(model.Device.label)
        .all()
    )


def get_memberships(user: model.User) -> List[str]:
    q = model.Membership.query
    q = q.filter(model.Membership.user == user.id)
    # inactive users are effectively not in any group
    q = q.filter(model.Membership.user_active)
    q = q.filter(model.Membership.group_active)
    q = q.filter(model.Membership.approved)
    ms = q.order_by(model.Membership.group).all()
    return [m.group for m in ms]


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


def get_group(which: str) -> Optional[model.Group]:
    return model.Group.query.get(which)


def get_members_of_group(group: model.Group) -> List[Tuple[str, bool]]:
    q = model.Membership.query
    q = q.filter(model.Membership.group == group.id)
    q = q.filter(model.Membership.user_active)
    q = q.filter(model.Membership.approved)
    return [(r.user, r.pi) for r in q.all()]


def is_admin(user: model.User) -> bool:
    q = model.Membership.query
    q = q.filter(model.Membership.user == user.id)
    q = q.filter(model.Membership.group == "admin")
    q = q.filter(model.Membership.user_active)
    q = q.filter(model.Membership.approved)
    return bool(q.first())


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


class JoinForm(FlaskForm):
    group = fields.StringField(
        label="department",
        validators=[validators.InputRequired()],
        render_kw={"list": "departments"},
    )

    def __init__(self, departments, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.departments = departments


def get_departments_for_join_form(db, user: model.User) -> List[Tuple[str, str]]:
    # get all active departments (and DEV group) that user is NOT a current or pending member of.
    q = db.session.execute(
        """
        select D.deptcode, D.dept from tlkpdept D
        where D.iscurrent and (D.department or D.deptcode = 'Dev') and deptcode not in (
            select M."group" from membership M where M."user" = :user
        ) order by 2;
    """,
        {"user": user.id},
    )
    return q.fetchall()
