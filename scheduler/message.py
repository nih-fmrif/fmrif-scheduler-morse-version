from smtplib import SMTPException
from typing import Mapping, Optional

from flask import current_app, g, has_request_context, request
from flask_mail import Mail, Message
from sqlalchemy.exc import SQLAlchemyError

mailer = Mail()


def _request_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    remote = (request.remote_addr or "").strip()
    return remote or "unknown"


def send(
    to: str,
    subj: str,
    msg: str,
    sender: Optional[str] = None,
    *,
    audit_context: Optional[Mapping[str, str]] = None,
) -> bool:
    m = Message()
    m.subject = subj
    m.body = msg
    addrs = [to]
    if "," in to:
        addrs = [s.strip() for s in to.split(",")]
    m.recipients = addrs
    # we only need to change the sender for the list action form
    if sender is not None:
        m.sender = sender
    ok = False
    try:
        mailer.send(m)
        if current_app.debug:
            current_app.logger.info("sent email to %s: %s / %s", to, subj, msg)
        ok = True
    except (SMTPException, OSError, AssertionError):
        # SMTP/socket failures should not break request handlers that already
        # persisted their primary DB-side changes.
        current_app.logger.exception("failed to send email to %s", to)

    metadata = dict(audit_context or {})
    action = str(metadata.get("action") or "email.send")
    how = str(metadata.get("how") or "general")
    details = str(metadata.get("details") or "")
    issue_key = str(metadata.get("issue_key") or "")
    issue_state = str(metadata.get("issue_state") or "")
    where = str(metadata.get("where") or "")
    actor = str(metadata.get("actor") or "")
    source_ip = str(metadata.get("source_ip") or "")

    if has_request_context():
        where = where or str(request.path or "")
        if source_ip == "":
            source_ip = _request_client_ip()
        if actor == "":
            current_user = getattr(g, "user", None)
            actor = str(getattr(current_user, "id", "") or "")

    where = where.strip() or "-"
    actor = actor.strip() or "system"

    try:
        from scheduler import logic

        logic.log_email_audit_event(
            action=action,
            actor=actor,
            where=where,
            how=how,
            status=(
                logic.EMAIL_AUDIT_STATUS_SENT if ok else logic.EMAIL_AUDIT_STATUS_FAILED
            ),
            recipient=to,
            subject=subj,
            details=details,
            issue_key=issue_key,
            issue_state=issue_state,
            source_ip=source_ip,
        )
    except (ImportError, AttributeError, RuntimeError, KeyError, SQLAlchemyError):
        current_app.logger.exception(
            "failed to persist email audit event action=%s recipient=%s",
            action,
            to,
        )

    return ok
