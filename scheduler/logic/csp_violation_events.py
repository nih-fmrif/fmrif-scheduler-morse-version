"""CSP violation event persistence helpers."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from scheduler import model

CSP_VIOLATION_EVENT_RETENTION_DAYS = 30
CSP_VIOLATION_EVENT_DEFAULT_LIMIT = 20

_CSP_VIOLATION_EVENT_TABLE_READY: Optional[bool] = None


def _csp_violation_event_inspection_bind() -> Any:
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


def _csp_violation_event_table_exists() -> bool:
    global _CSP_VIOLATION_EVENT_TABLE_READY
    if _CSP_VIOLATION_EVENT_TABLE_READY is True:
        return True
    try:
        exists = inspect(_csp_violation_event_inspection_bind()).has_table(
            "csp_violation_event"
        )
    except SQLAlchemyError:
        return False
    if exists:
        _CSP_VIOLATION_EVENT_TABLE_READY = True
    return exists


def csp_violation_event_table_available() -> bool:
    return _csp_violation_event_table_exists()


def record_csp_violation_event(
    *,
    report_type: str,
    actor: str,
    ip_addr: str,
    user_agent: str,
    document_uri: str,
    referrer: str,
    blocked_uri: str,
    violated_directive: str,
    effective_directive: str,
    original_policy: str,
    source_file: str,
    line_number: Optional[int],
    column_number: Optional[int],
    disposition: str,
    status_code: Optional[int],
    script_sample: str,
    report_body: Dict[str, Any],
    occurred_at: Optional[datetime.datetime] = None,
) -> bool:
    if not csp_violation_event_table_available():
        return False

    now = occurred_at or datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=CSP_VIOLATION_EVENT_RETENTION_DAYS)
    values = {
        "report_type": (report_type or "").strip() or "csp-violation",
        "actor": (actor or "").strip() or "anonymous",
        "ip_addr": (ip_addr or "").strip() or None,
        "user_agent": (user_agent or "").strip(),
        "document_uri": (document_uri or "").strip(),
        "referrer": (referrer or "").strip() or None,
        "blocked_uri": (blocked_uri or "").strip() or None,
        "violated_directive": (violated_directive or "").strip(),
        "effective_directive": (effective_directive or "").strip() or None,
        "original_policy": (original_policy or "").strip() or None,
        "source_file": (source_file or "").strip() or None,
        "line_number": int(line_number) if line_number is not None else None,
        "column_number": int(column_number) if column_number is not None else None,
        "disposition": (disposition or "").strip() or "enforce",
        "status_code": int(status_code) if status_code is not None else None,
        "script_sample": (script_sample or "").strip() or None,
        "report_body": dict(report_body or {}),
        "occurred_at": now,
    }

    bind = _csp_violation_event_inspection_bind()

    def _write(connection: Any) -> None:
        connection.execute(
            model.CspViolationEvent.__table__.delete().where(
                model.CspViolationEvent.occurred_at < cutoff
            )
        )
        connection.execute(model.CspViolationEvent.__table__.insert().values(**values))

    if isinstance(bind, Connection):
        _write(bind)
    else:
        with model.db.engine.begin() as connection:
            _write(connection)
    return True


def csp_violation_event_rows(*, limit: int) -> List[model.CspViolationEvent]:
    if not csp_violation_event_table_available():
        return []

    statement = (
        select(model.CspViolationEvent)
        .order_by(
            model.CspViolationEvent.occurred_at.desc(),
            model.CspViolationEvent.id.desc(),
        )
        .limit(max(1, int(limit)))
    )
    return model.db.session.execute(statement).scalars().all()


def csp_violation_event_payload(row: model.CspViolationEvent) -> Dict[str, Any]:
    occurred_at = row.occurred_at
    when = ""
    if occurred_at is not None:
        when = (
            occurred_at.isoformat()
            if hasattr(occurred_at, "isoformat")
            else str(occurred_at)
        )

    report_body = row.report_body
    if not isinstance(report_body, dict):
        report_body = {}

    return {
        "id": row.id,
        "when": when,
        "report_type": row.report_type or "",
        "actor": row.actor or "",
        "ip": row.ip or "",
        "user_agent": row.user_agent or "",
        "document_uri": row.document_uri or "",
        "referrer": row.referrer or "",
        "blocked_uri": row.blocked_uri or "",
        "violated_directive": row.violated_directive or "",
        "effective_directive": row.effective_directive or "",
        "original_policy": row.original_policy or "",
        "source_file": row.source_file or "",
        "line_number": row.line_number,
        "column_number": row.column_number,
        "disposition": row.disposition or "",
        "status_code": row.status_code,
        "script_sample": row.script_sample or "",
        "report_body": report_body,
    }


__all__ = [
    "CSP_VIOLATION_EVENT_DEFAULT_LIMIT",
    "CSP_VIOLATION_EVENT_RETENTION_DAYS",
    "csp_violation_event_payload",
    "csp_violation_event_rows",
    "csp_violation_event_table_available",
    "record_csp_violation_event",
]
