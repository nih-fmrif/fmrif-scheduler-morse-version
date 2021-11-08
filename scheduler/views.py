from flask import current_app
from flask_mail import Message


def send_msg(to: str, subj: str, msg: str) -> None:
    mail = current_app.config["SESSION_MAILER"]
    m = Message()
    m.subject = to
    m.body = msg
    addrs = [to]
    if "," in to:
        addrs = [s.strip() for s in to.split(",")]
    m.recipients = addrs
    mail.send(m)
    if current_app.debug:
        current_app.logger.info("sent email to %s: %s / %s", to, subj, msg)


def index():
    routes = []
    # TODO add routes as they're added to the app, checking for visibility first if required
    return {"routes": routes}
