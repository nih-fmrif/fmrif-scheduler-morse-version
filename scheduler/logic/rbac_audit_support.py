"""RBAC and email audit helpers."""

import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

import itsdangerous
from flask import current_app
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from scheduler import model

_RBAC_AUDIT_KV_PATTERN = re.compile(
    r"([a-z_]+)=([^,]+(?:,(?!\s*[a-z_]+=)[^,]+)*)",
    flags=re.IGNORECASE,
)
_RBAC_AUDIT_GROUP_PATH_PATTERN = re.compile(r"^/group/([^/]+)")
_RBAC_AUDIT_JOIN_PATH_PATTERN = re.compile(r"^/join/(?:(?:approve|deny)/)?([^/]+)$")
_RBAC_AUDIT_DEVICE_PATH_PATTERN = re.compile(r"^/device/([^/]+)")
_RBAC_AUDIT_TABLE_READY: Optional[bool] = None
_RBAC_AUDIT_IP_COLUMN_READY: Optional[bool] = None
_EMAIL_AUDIT_TABLE_READY: Optional[bool] = None
_NOTIFICATION_INCIDENT_TABLE_READY: Optional[bool] = None
EMAIL_STATUS_NONE = "none"
EMAIL_STATUS_SENT = "sent"
EMAIL_STATUS_FAILED = "failed"
EMAIL_STATUS_VALUES = (
    EMAIL_STATUS_NONE,
    EMAIL_STATUS_SENT,
    EMAIL_STATUS_FAILED,
)
EMAIL_AUDIT_STATUS_SENT = "sent"
EMAIL_AUDIT_STATUS_FAILED = "failed"
EMAIL_AUDIT_STATUS_RESOLVED = "resolved"
EMAIL_AUDIT_STATUS_SKIPPED = "skipped"
EMAIL_AUDIT_STATUS_VALUES = (
    EMAIL_AUDIT_STATUS_SENT,
    EMAIL_AUDIT_STATUS_FAILED,
    EMAIL_AUDIT_STATUS_RESOLVED,
    EMAIL_AUDIT_STATUS_SKIPPED,
)
EMAIL_AUDIT_ISSUE_NONE = "none"
EMAIL_AUDIT_ISSUE_OPEN = "open"
EMAIL_AUDIT_ISSUE_RESOLVED = "resolved"
EMAIL_AUDIT_ISSUE_STATE_VALUES = (
    EMAIL_AUDIT_ISSUE_NONE,
    EMAIL_AUDIT_ISSUE_OPEN,
    EMAIL_AUDIT_ISSUE_RESOLVED,
)


def _rbac_audit_inspection_bind() -> Any:
    try:
        bind = model.db.session.bind
        if bind is not None:
            return bind
    except (AttributeError, RuntimeError, TypeError):
        pass
    try:
        bind = model.db.session().get_bind()
        if bind is not None:
            return bind
    except (AttributeError, RuntimeError, TypeError):
        pass
    return model.db.engine


def _rbac_audit_table_exists() -> bool:
    global _RBAC_AUDIT_TABLE_READY
    if _RBAC_AUDIT_TABLE_READY is True:
        return True
    try:
        exists = inspect(_rbac_audit_inspection_bind()).has_table("rbac_audit_log")
    except SQLAlchemyError:
        return False
    if exists:
        _RBAC_AUDIT_TABLE_READY = True
    return exists


def rbac_audit_table_available() -> bool:
    return _rbac_audit_table_exists()


def _email_audit_table_exists() -> bool:
    global _EMAIL_AUDIT_TABLE_READY
    if _EMAIL_AUDIT_TABLE_READY is True:
        return True
    try:
        exists = inspect(_rbac_audit_inspection_bind()).has_table("email_audit_log")
    except SQLAlchemyError:
        return False
    if exists:
        _EMAIL_AUDIT_TABLE_READY = True
    return exists


def email_audit_table_available() -> bool:
    return _email_audit_table_exists()


def _notification_incident_table_exists() -> bool:
    global _NOTIFICATION_INCIDENT_TABLE_READY
    if _NOTIFICATION_INCIDENT_TABLE_READY is True:
        return True
    try:
        exists = inspect(_rbac_audit_inspection_bind()).has_table(
            "notification_incident"
        )
    except SQLAlchemyError:
        return False
    if exists:
        _NOTIFICATION_INCIDENT_TABLE_READY = True
    return exists


def notification_incident_table_available() -> bool:
    return _notification_incident_table_exists()


def _rbac_audit_ip_column_exists() -> bool:
    global _RBAC_AUDIT_IP_COLUMN_READY
    if _RBAC_AUDIT_IP_COLUMN_READY is True:
        return True
    if not _rbac_audit_table_exists():
        return False
    try:
        columns = {
            column["name"]
            for column in inspect(_rbac_audit_inspection_bind()).get_columns(
                "rbac_audit_log"
            )
        }
        has_ip_column = "ip_addr" in columns
    except SQLAlchemyError:
        return False
    if has_ip_column:
        _RBAC_AUDIT_IP_COLUMN_READY = True
    return has_ip_column


def rbac_audit_ip_column_available() -> bool:
    return _rbac_audit_ip_column_exists()


def _parse_rbac_audit_details(what: str) -> Dict[str, str]:
    details: Dict[str, str] = {}
    for key, raw_value in _RBAC_AUDIT_KV_PATTERN.findall(what or ""):
        value = raw_value.strip()
        if value == "":
            continue
        details[key.strip().lower()] = value
    return details


def _infer_rbac_audit_targets(
    where: str, details: Dict[str, str]
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    group_id = details.get("group")
    device_id = details.get("device")
    user_id = details.get("user")
    requester_id = details.get("requester")

    if user_id is None:
        user_id = details.get("to")

    where_path = where or ""

    if group_id is None:
        group_match = _RBAC_AUDIT_GROUP_PATH_PATTERN.match(where_path)
        if group_match:
            group_id = group_match.group(1)
        else:
            join_match = _RBAC_AUDIT_JOIN_PATH_PATTERN.match(where_path)
            if join_match and join_match.group(1) != "tech":
                group_id = join_match.group(1)

    if device_id is None:
        device_match = _RBAC_AUDIT_DEVICE_PATH_PATTERN.match(where_path)
        if device_match:
            device_id = device_match.group(1)

    return group_id, device_id, user_id, requester_id


def _audit_target_value(value: Optional[str]) -> Optional[str]:
    token = (value or "").strip()
    if token == "":
        return None
    return token


def _record_rbac_audit_event(
    action: str,
    actor: str,
    where: str,
    how: str,
    what: str,
    source_ip: str = "",
) -> None:
    if not _rbac_audit_table_exists():
        return

    ip = (source_ip or "").strip()
    stored_what = what
    if ip != "" and "ip=" not in (stored_what or "").lower():
        stored_what = f"{stored_what}, ip={ip}" if stored_what else f"ip={ip}"

    details = _parse_rbac_audit_details(stored_what)
    group_id, device_id, user_id, requester_id = _infer_rbac_audit_targets(
        where, details
    )
    group_id = _audit_target_value(group_id)
    device_id = _audit_target_value(device_id)
    user_id = _audit_target_value(user_id)
    requester_id = _audit_target_value(requester_id)
    base_params = {
        "action": action,
        "actor": actor,
        "where_path": where,
        "how": how,
        "what": stored_what,
        "deptcode": group_id,
        "scannercode": device_id,
        "researchercode": user_id,
        "requestercode": requester_id,
    }
    if _rbac_audit_ip_column_exists():
        params = {
            **base_params,
            "ip_addr": ip or None,
        }
        model.db.session.execute(
            text(
                """
                insert into rbac_audit_log (
                    action, actor, ip_addr, where_path, how, what,
                    deptcode, scannercode, researchercode, requestercode
                ) values (
                    :action, :actor, :ip_addr, :where_path, :how, :what,
                    :deptcode, :scannercode, :researchercode, :requestercode
                )
                """
            ),
            params,
        )
        return
    model.db.session.execute(
        text(
            """
            insert into rbac_audit_log (
                action, actor, where_path, how, what,
                deptcode, scannercode, researchercode, requestercode
            ) values (
                :action, :actor, :where_path, :how, :what,
                :deptcode, :scannercode, :researchercode, :requestercode
            )
            """
        ),
        base_params,
    )


def log_rbac_audit_event(
    action: str,
    actor: str,
    where: str,
    how: str,
    what: str,
    source_ip: str = "",
) -> None:
    """Log RBAC mutations with a dedicated category prefix.

    The message format is stable for easier filtering in log pipelines:
      RBAC_AUDIT action=... actor=... ip=... where=... when=... how=... what=...
    """
    current_app.logger.info(
        "RBAC_AUDIT action=%s actor=%s ip=%s where=%s when=%s how=%s what=%s",
        action,
        actor,
        source_ip or "",
        where,
        datetime.datetime.now(datetime.timezone.utc).isoformat(),
        how,
        what,
    )
    try:
        _record_rbac_audit_event(
            action=action,
            actor=actor,
            where=where,
            how=how,
            what=what,
            source_ip=source_ip,
        )
    except SQLAlchemyError:
        current_app.logger.exception("Failed to persist RBAC_AUDIT record")


def _email_audit_status(value: str, *, default: str = EMAIL_AUDIT_STATUS_FAILED) -> str:
    token = (value or "").strip().lower()
    if token in EMAIL_AUDIT_STATUS_VALUES:
        return token
    return default


def _email_audit_issue_state(
    value: str, *, default: str = EMAIL_AUDIT_ISSUE_NONE
) -> str:
    token = (value or "").strip().lower()
    if token in EMAIL_AUDIT_ISSUE_STATE_VALUES:
        return token
    return default


def _record_email_audit_event(
    action: str,
    actor: str,
    where: str,
    how: str,
    *,
    status: str,
    recipient: str,
    subject: str,
    details: str,
    issue_key: str = "",
    issue_state: str = "",
    source_ip: str = "",
) -> None:
    if not _email_audit_table_exists():
        return

    stored_details = (details or "").strip()
    ip = (source_ip or "").strip()
    if ip != "" and "ip=" not in stored_details.lower():
        stored_details = f"{stored_details}, ip={ip}" if stored_details else f"ip={ip}"
    parsed = _parse_rbac_audit_details(stored_details)
    group_id, device_id, user_id, requester_id = _infer_rbac_audit_targets(
        where, parsed
    )
    group_id = _audit_target_value(group_id)
    device_id = _audit_target_value(device_id)
    user_id = _audit_target_value(user_id)
    requester_id = _audit_target_value(requester_id)
    issue_key_value = (issue_key or "").strip() or None
    issue_state_value = _email_audit_issue_state(
        issue_state,
        default=(
            EMAIL_AUDIT_ISSUE_OPEN
            if _email_audit_status(status) == EMAIL_AUDIT_STATUS_FAILED
            and issue_key_value is not None
            else EMAIL_AUDIT_ISSUE_NONE
        ),
    )

    model.db.session.execute(
        text(
            """
            insert into email_audit_log (
                action, actor, ip_addr, where_path, how, status,
                recipient, subject, details, issue_key, issue_state,
                deptcode, scannercode, researchercode, requestercode
            ) values (
                :action, :actor, :ip_addr, :where_path, :how, :status,
                :recipient, :subject, :details, :issue_key, :issue_state,
                :deptcode, :scannercode, :researchercode, :requestercode
            )
            """
        ),
        {
            "action": action,
            "actor": actor,
            "ip_addr": ip or None,
            "where_path": where,
            "how": how,
            "status": _email_audit_status(status),
            "recipient": recipient,
            "subject": subject,
            "details": stored_details,
            "issue_key": issue_key_value,
            "issue_state": issue_state_value,
            "deptcode": group_id,
            "scannercode": device_id,
            "researchercode": user_id,
            "requestercode": requester_id,
        },
    )


def log_email_audit_event(
    action: str,
    actor: str,
    where: str,
    how: str,
    *,
    status: str,
    recipient: str,
    subject: str,
    details: str,
    issue_key: str = "",
    issue_state: str = "",
    source_ip: str = "",
) -> None:
    """Log email delivery and issue lifecycle events."""
    status_value = _email_audit_status(status)
    issue_state_value = _email_audit_issue_state(
        issue_state,
        default=(
            EMAIL_AUDIT_ISSUE_OPEN
            if status_value == EMAIL_AUDIT_STATUS_FAILED
            and (issue_key or "").strip() != ""
            else EMAIL_AUDIT_ISSUE_NONE
        ),
    )
    current_app.logger.info(
        (
            "EMAIL_AUDIT "
            f"action={action} actor={actor} ip={source_ip or ''} "
            f"where={where} when={datetime.datetime.now(datetime.timezone.utc).isoformat()} "
            f"how={how} status={status_value} issue_key={issue_key or ''} "
            f"issue_state={issue_state_value} recipient={recipient} "
            f"subject={subject} details={details}"
        ),
    )
    try:
        _record_email_audit_event(
            action=action,
            actor=actor,
            where=where,
            how=how,
            status=status_value,
            recipient=recipient,
            subject=subject,
            details=details,
            issue_key=issue_key,
            issue_state=issue_state_value,
            source_ip=source_ip,
        )
    except SQLAlchemyError:
        current_app.logger.exception("Failed to persist EMAIL_AUDIT record")


def log_email_issue_resolution(
    *,
    issue_key: str,
    actor: str,
    where: str,
    how: str,
    details: str,
    source_ip: str = "",
) -> None:
    issue_token = (issue_key or "").strip()
    if issue_token == "":
        return
    log_email_audit_event(
        action="email.issue.resolved",
        actor=actor or "unknown",
        where=where,
        how=how,
        status=EMAIL_AUDIT_STATUS_RESOLVED,
        recipient="-",
        subject="notification issue resolved",
        details=details,
        issue_key=issue_token,
        issue_state=EMAIL_AUDIT_ISSUE_RESOLVED,
        source_ip=source_ip,
    )


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
        for value in result:
            if not isinstance(value, str):
                return None
        return result
    except itsdangerous.exc.BadData:
        return None


__all__ = [
    "EMAIL_STATUS_NONE",
    "EMAIL_STATUS_SENT",
    "EMAIL_STATUS_FAILED",
    "EMAIL_STATUS_VALUES",
    "EMAIL_AUDIT_STATUS_SENT",
    "EMAIL_AUDIT_STATUS_FAILED",
    "EMAIL_AUDIT_STATUS_RESOLVED",
    "EMAIL_AUDIT_STATUS_SKIPPED",
    "EMAIL_AUDIT_STATUS_VALUES",
    "EMAIL_AUDIT_ISSUE_NONE",
    "EMAIL_AUDIT_ISSUE_OPEN",
    "EMAIL_AUDIT_ISSUE_RESOLVED",
    "EMAIL_AUDIT_ISSUE_STATE_VALUES",
    "constraint_of",
    "sign_message",
    "read_signed_message",
    "rbac_audit_table_available",
    "rbac_audit_ip_column_available",
    "email_audit_table_available",
    "notification_incident_table_available",
    "log_rbac_audit_event",
    "log_email_audit_event",
    "log_email_issue_resolution",
]
