from typing import Any, Generator, List, Optional, Tuple, cast

import itsdangerous
from flask import current_app
from flask_mail import Message
from flask_wtf import FlaskForm
from wtforms import fields, validators

import model


def send_msg(to: str, subj: str, msg: str, sender: Optional[str] = None) -> None:
    mail = current_app.config["SESSION_MAILER"]
    m = Message()
    m.subject = to
    m.body = msg
    addrs = [to]
    if "," in to:
        addrs = [s.strip() for s in to.split(",")]
    m.recipients = addrs
    # we only need to change the sender for the list action form
    if sender is not None:
        m.sender = sender
    mail.send(m)
    if current_app.debug:
        current_app.logger.info("sent email to %s: %s / %s", to, subj, msg)


def get_mailing_list_form(**kwargs):
    # create the dynamic part of the form from the app settings
    class MailingListsSubform(FlaskForm):
        def all_checkboxes(self) -> Generator[Tuple[str, bool], None, None]:
            for elm in self:
                current_app.logger.info(elm.type)
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
        send_msg(listserv, "Automated list change", msg, sender=addr)


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


def is_admin(user: model.User) -> bool:
    q = model.Membership.query
    q = q.filter(model.Membership.user == user.id)
    q = q.filter(model.Membership.group == "admin")
    q = q.filter(model.Membership.user_active)
    q = q.filter(model.Membership.approved)
    return bool(q.first())


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
