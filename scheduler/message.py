from smtplib import SMTPException
from typing import Optional

from flask import current_app
from flask_mail import Mail, Message

mailer = Mail()


def send(to: str, subj: str, msg: str, sender: Optional[str] = None) -> bool:
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
    try:
        mailer.send(m)
        if current_app.debug:
            current_app.logger.info("sent email to %s: %s / %s", to, subj, msg)
        return True
    except SMTPException as e:
        current_app.logger.warn(e)
        return False
