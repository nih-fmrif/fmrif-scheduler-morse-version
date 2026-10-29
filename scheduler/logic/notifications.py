"""Notification and messaging helpers."""

from typing import Any, Generator, List, Optional, Tuple

from flask import current_app, url_for
from flask_wtf import FlaskForm
from sqlalchemy import or_, select
from wtforms import Form, fields, validators

from scheduler import message, model

from .rbac_audit_support import EMAIL_STATUS_FAILED, EMAIL_STATUS_SENT, sign_message
from .schedule_editor import fmt_hours

Datalist = List[Tuple[str, str]]


def _normalize_name(name: str) -> str:
    if "," in name:
        last, first = [segment.strip() for segment in name.split(",", 1)]
        return f"{first} {last}"
    return name.strip()


def _get_user(user_id: str) -> Optional[model.User]:
    return model.db.session.get(model.User, user_id)


def _get_dev_pi_recipient() -> Optional[model.User]:
    membership_model = model.Membership
    membership_statement = (
        select(membership_model)
        .where(membership_model.group == "DEV")
        .where(membership_model.pi)
    )
    membership = model.db.session.scalars(membership_statement).first()
    if membership is None:
        current_app.logger.warning("no DEV PI found")
        return None

    dev_pi = _get_user(membership.user)
    if dev_pi is None:
        current_app.logger.warning("no DEV PI user found for id %s", membership.user)
        return None
    if dev_pi.addr == "":
        current_app.logger.warning("could not find email address for dev pi")
        return None
    return dev_pi


def notify_dev_pi_of_tech_join_form(user: model.User) -> str:
    current_app.logger.info("%s submitted the technologist join form", user.id)
    dev_pi = _get_dev_pi_recipient()
    if dev_pi is None:
        return EMAIL_STATUS_FAILED

    token = sign_message(["join-tech", user.id, "DEV"])
    approve = url_for("join-group-approve", token=token)
    deny = url_for("join-group-deny", token=token)
    page = url_for("rbac", scope="user", entity=user.id)

    ok = message.send(
        dev_pi.addr,
        f"{user.id} has requested technologist access",
        f"""
{user.id} has requested technologist access.

click to approve: {approve}

click to deny: {deny}

or go to {page} to manage this user in RBAC explorer.
        """.strip(),
        audit_context={
            "action": "email.join.tech.notify-dev-pi",
            "how": "join-tech-request",
            "details": f"group=DEV, requester={user.id}, pi={dev_pi.id}",
            "issue_key": f"join-tech:DEV:{user.id}",
        },
    )
    return EMAIL_STATUS_SENT if ok else EMAIL_STATUS_FAILED


def notify_dev_pi_of_tech_autoapproval(user: model.User) -> str:
    current_app.logger.info("%s was auto-approved for technologist access", user.id)
    dev_pi = _get_dev_pi_recipient()
    if dev_pi is None:
        return EMAIL_STATUS_FAILED

    page = url_for("rbac", scope="user", entity=user.id)

    ok = message.send(
        dev_pi.addr,
        f"{user.id} was granted technologist access",
        f"""
{user.id} was granted technologist access automatically via the technologist join form.

go to {page} to review this user in RBAC explorer.
        """.strip(),
        audit_context={
            "action": "email.join.tech.autoapprove.notify-dev-pi",
            "how": "join-tech-autoapprove",
            "details": f"group=DEV, requester={user.id}, pi={dev_pi.id}",
        },
    )
    return EMAIL_STATUS_SENT if ok else EMAIL_STATUS_FAILED


def get_departments_for_join_form(user: model.User) -> Datalist:
    membership_groups = select(model.Membership.group).where(
        model.Membership.user == user.id
    )
    query = model.db.session.execute(
        select(model.Group.id, model.Group.description)
        .where(model.Group.active.is_(True))
        .where(or_(model.Group.department.is_(True), model.Group.id == "DEV"))
        .where(~model.Group.id.in_(membership_groups))
        .order_by(model.Group.description)
    )
    out = []
    for group_id, label in query.fetchall():
        if label != group_id:
            label = f"{label} ({group_id})"
        out.append((group_id, label))
    return out


def get_mailing_list_form(**kwargs):
    class MailingListsSubform(Form):
        def all_checkboxes(self) -> Generator[Tuple[str, bool], None, None]:
            for element in self:
                if element.type == "BooleanField":
                    yield (element.label.text, element.data)

        def validate(self) -> bool:
            if not Form.validate(self):
                return False

            if not any(entry[1] for entry in self.all_checkboxes()):
                self.form_errors.append("At least one list must be selected")
                return False
            return True

    from ._admin_config_settings import get_admin_mailing_lists

    lists = get_admin_mailing_lists().items()
    for idx, (name, description) in enumerate(lists):
        setattr(
            MailingListsSubform,
            f"ml-{idx}",
            fields.BooleanField(label=name, description=description),
        )

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
        lists = fields.FormField(MailingListsSubform, label="lists")
        action = fields.RadioField(label="action", choices=choices, default="sub")

        def validate_addr(self, addr) -> None:
            if "," in addr.data:
                raise validators.ValidationError("only one email address allowed")
            if "@" not in addr.data:
                raise validators.ValidationError("email address must contain @")
            _, domain = addr.data.split("@", 1)
            if not domain.endswith("nih.gov"):
                raise validators.ValidationError("only nih.gov email addresses allowed")

    return MailingListForm(**kwargs)


def process_mailing_list_form_submissions(form):
    from ._admin_config_settings import get_admin_listserv

    selected_lists = [item[0] for item in form.lists.all_checkboxes() if item[1]]
    addr = form.addr.data
    name = _normalize_name(form.name.data)
    sub = form.action.data == "sub"
    listserv = get_admin_listserv()
    for list_name in selected_lists:
        msg = format_mailing_list_message(sub, list_name, name)
        message.send(
            listserv,
            "Automated list change",
            msg,
            sender=addr,
            audit_context={
                "action": "email.mailing-list.change",
                "how": "mailing-list",
                "details": (
                    f"list={list_name}, action={'subscribe' if sub else 'unsubscribe'}, "
                    f"requester={addr}"
                ),
            },
        )


def format_mailing_list_message(sub: bool, which_list: str, name: str) -> str:
    if sub:
        return f"subscribe {which_list} {name}"
    return f"signoff {which_list}"


def notify_group_pi_of_join_form(user: model.User, group: str) -> str:
    grp = model.db.session.get(model.Group, group)
    if grp is None:
        raise RuntimeError(
            f"{user.id} attempted to join group that does not exist: {group}"
        )

    current_app.logger.info("%s has requested to join %s", user.id, group)

    membership_model = model.Membership
    membership_statement = (
        select(membership_model)
        .where(membership_model.group == group)
        .where(membership_model.pi)
    )
    membership = model.db.session.scalars(membership_statement).first()
    if membership is None:
        current_app.logger.warning("no PI to notify for %s joining %s", user.id, group)
        return EMAIL_STATUS_FAILED

    pi_user = _get_user(membership.user)
    if pi_user is None:
        current_app.logger.warning(
            "no PI user found for %s joining %s: %s", user.id, group, membership.user
        )
        return EMAIL_STATUS_FAILED
    if pi_user.addr == "":
        current_app.logger.warning(
            "no address to notify PI %s about %s joining %s",
            pi_user.id,
            user.id,
            group,
        )
        return EMAIL_STATUS_FAILED

    token = sign_message(["join-group", user.id, group])
    approve = url_for("join-group-approve", token=token)
    deny = url_for("join-group-deny", token=token)
    page = url_for("rbac", scope="group", entity=group)
    ok = message.send(
        pi_user.addr,
        f"{user.id} has requested to join {group}",
        f"""
{user.id} has requested to join {group}

click to approve: {approve}

click to deny: {deny}

or go to {page} to manage membership in RBAC for {group}.
        """.strip(),
        audit_context={
            "action": "email.join.notify-group-pi",
            "how": "join-request",
            "details": f"group={group}, requester={user.id}, pi={pi_user.id}",
            "issue_key": f"join-group:{group}:{user.id}",
        },
    )
    return EMAIL_STATUS_SENT if ok else EMAIL_STATUS_FAILED


def notify_user_of_join_request_outcome(
    approved: bool, user: model.User, group: str
) -> None:
    if "@" not in user.addr:
        current_app.logger.info(
            "could not notify %s of group membership change due to lack of address on file",
            user.id,
        )
        return

    outcome = "approved" if approved else "denied"
    msg = f"your request to join {group} was {outcome}"
    message.send(
        user.addr,
        msg,
        msg,
        audit_context={
            "action": "email.join.outcome",
            "how": "join-request-outcome",
            "details": f"group={group}, user={user.id}, outcome={outcome}",
        },
    )


def notify_user_of_tech_join_request_outcome(approved: bool, user: model.User) -> None:
    if "@" not in user.addr:
        current_app.logger.info(
            "could not notify %s of technologist status change due to lack of address on file",
            user.id,
        )
        return

    outcome = "approved" if approved else "denied"
    msg = f"your request for technologist access was {outcome}"
    message.send(
        user.addr,
        msg,
        msg,
        audit_context={
            "action": "email.join.tech.outcome",
            "how": "join-tech-outcome",
            "details": f"group=DEV, user={user.id}, outcome={outcome}",
        },
    )


def prepare_notifications(send_notifications, when, diffs, srs_notes):
    # filter out diffs that won't cause a notification
    if not send_notifications:
        return [], {
            "schedule": [],
            "training": [],
            "medical": [],
            "technologist": [],
        }

    diffs_out = []
    for diff in diffs:
        entry_id = int(diff["id"])
        # old entry
        if when[entry_id][0]:
            continue
        # only has SR
        if not any(key in diff for key in ("group", "member")):
            continue
        diffs_out.append(diff)

    srs_out = {
        "schedule": [],
        "training": [],
        "medical": [],
        "technologist": [],
    }
    for note in srs_notes:
        old, date, hour = when[note["id"]]
        if old:
            continue
        with_time = (date, hour, note)
        srs_out["schedule"].append(with_time)
        srs_out[note["kind"]].append(with_time)

    return diffs_out, srs_out


def fmt_notifications(ens, sns):
    hours = fmt_hours()
    schedule = fmt_regular_notifications(hours, ens)
    sr_schedule = fmt_support_notifications(hours, sns["schedule"], True)
    if sr_schedule:
        # both regular and SR notifications, add separator
        if schedule:
            schedule += "\n"
        schedule += "Support Requests\n" + sr_schedule
    out = {"schedule": schedule}
    for kind in ("training", "medical", "technologist"):
        out[kind] = fmt_support_notifications(hours, sns[kind], False)
    return out


def fmt_regular_notifications(hours, ens):
    if len(ens) == 0:
        return ""
    acc = []

    def push(text):
        acc.append(text)

    def push_state(what, old, new):
        if old == "":
            push(f"\tset {what} to {new}")
        elif new == "":
            push(f"\tcleared {what} (was {old})")
        else:
            push(f"\tchanged {what} from {old} to {new}")

    for entry in ens:
        hour = hours[int(entry["hour"])]
        push(f"{entry['date']}: {hour}")
        if "group" in entry:
            push_state("group", *entry["group"])
        if "member" in entry:
            push_state("member", *entry["member"])

    return "\n".join(acc)


def fmt_support_notifications(hours, sns, include_kind):
    if len(sns) == 0:
        return ""
    acc = []

    def push(text):
        acc.append(text)

    # if we're including kind, double indent
    indent = "\t"
    if include_kind:
        indent = "\t\t"

    last_section = ""
    for date, hour, note in sns:
        # if this is for the regular email, there may be multiple SR changes in a row,
        # if so, we only want to add the section header once
        section = f"{date}: {hours[hour]}"
        if section != last_section:
            push(section)
            last_section = section
        if include_kind:
            push(f"\t{note['kind']}")

        state = note["state"]
        if state == "new":
            push(f"{indent}new request")
        elif state == "updated":
            push(f"{indent}request updated")
        elif state == "retracted":
            push(f"{indent}request retracted")
        elif state == "denied":
            push(f"{indent}request denied")
        elif state == "canceled":
            push(f"{indent}request canceled")
        elif state == "unassigned":
            push(f"{indent}request no longer has handler but still open")
        elif state == "reassigned":
            push(f"{indent}request reassigned to new handler")
        elif state == "approved":
            push(f"{indent}request approved")

        if "handler" in note:
            push(f"{indent}to be handled by {note['handler']}")

        if "subkind" in note:
            push(f"{indent}scan/cover set to {note['subkind'][1]}")

    return "\n".join(acc)


def send_scheduler_notifications(device: model.Device, msgs: dict[str, str]):
    streams = (
        ("schedule", device.addr, "schedule change"),
        ("training", device.train_addr, "training request change"),
        ("medical", device.med_addr, "medical coverage request change"),
        ("technologist", device.tech_addr, "technologist request change"),
    )
    notes: list[dict[str, Any]] = []
    for key, addr, subj in streams:
        msg = msgs[key]
        if msg == "":
            continue

        def note(what):
            notes.append({"key": key, "msg": what})

        if "@" not in addr:
            note("address")
            continue

        subject = f"[scheduler] {device.label}: {key} {subj}"
        ok = message.send(
            addr,
            subject,
            msg,
            audit_context={
                "action": "email.scheduler.notification",
                "how": "scheduler",
                "details": f"device={device.id}, stream={key}",
            },
        )
        if not ok:
            note("failed")
        elif current_app.config.get("MAIL_SUPPRESS_SEND", False):
            note("skipped")
        else:
            note("success")

    return notes


__all__ = [
    "EMAIL_STATUS_SENT",
    "EMAIL_STATUS_FAILED",
    "notify_dev_pi_of_tech_autoapproval",
    "notify_dev_pi_of_tech_join_form",
    "notify_group_pi_of_join_form",
    "notify_user_of_join_request_outcome",
    "notify_user_of_tech_join_request_outcome",
    "get_departments_for_join_form",
    "get_mailing_list_form",
    "process_mailing_list_form_submissions",
    "format_mailing_list_message",
    "prepare_notifications",
    "fmt_notifications",
    "fmt_regular_notifications",
    "fmt_support_notifications",
    "send_scheduler_notifications",
]
