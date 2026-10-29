"""Application error event persistence and query helpers."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import inspect, or_
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from scheduler import model

APP_ERROR_EVENT_RETENTION_DAYS = 180
APP_ERROR_EVENT_DEFAULT_LIMIT = 10
APP_ERROR_EVENT_MAX_LIMIT = 200

_APP_ERROR_EVENT_TABLE_READY: Optional[bool] = None


def _app_error_event_inspection_bind() -> Any:
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


def _app_error_event_table_exists() -> bool:
    global _APP_ERROR_EVENT_TABLE_READY
    if _APP_ERROR_EVENT_TABLE_READY is True:
        return True
    try:
        exists = inspect(_app_error_event_inspection_bind()).has_table(
            "app_error_event"
        )
    except SQLAlchemyError:
        return False
    if exists:
        _APP_ERROR_EVENT_TABLE_READY = True
    return exists


def app_error_event_table_available() -> bool:
    return _app_error_event_table_exists()


def record_app_error_event(
    *,
    reference_id: str,
    actor: str,
    ip_addr: str,
    user_agent: str,
    method: str,
    where_path: str,
    endpoint: str,
    status_code: int,
    exception_type: str,
    exception_message: str,
    fingerprint: str,
    request_context: Dict[str, Any],
    stack_trace: str,
    occurred_at: Optional[datetime.datetime] = None,
) -> bool:
    if not app_error_event_table_available():
        return False

    now = occurred_at or datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=APP_ERROR_EVENT_RETENTION_DAYS)
    values = {
        "reference_id": (reference_id or "").strip(),
        "actor": (actor or "").strip() or "anonymous",
        "ip_addr": (ip_addr or "").strip() or None,
        "user_agent": (user_agent or "").strip(),
        "method": (method or "").strip().upper() or "GET",
        "where_path": (where_path or "").strip() or "-",
        "endpoint": (endpoint or "").strip() or None,
        "status_code": int(status_code or 500),
        "exception_type": (exception_type or "").strip() or "Exception",
        "exception_message": (exception_message or "").strip()
        or "Unhandled application error",
        "fingerprint": (fingerprint or "").strip() or "unknown",
        "request_context": dict(request_context or {}),
        "stack_trace": stack_trace or "",
        "occurred_at": now,
    }

    bind = _app_error_event_inspection_bind()

    def _write(connection: Any) -> None:
        connection.execute(
            model.AppErrorEvent.__table__.delete().where(
                model.AppErrorEvent.occurred_at < cutoff
            )
        )
        connection.execute(model.AppErrorEvent.__table__.insert().values(**values))

    if isinstance(bind, Connection):
        _write(bind)
    else:
        with model.db.engine.begin() as connection:
            _write(connection)
    return True


def app_error_event_rows(
    *,
    limit: int,
    actor: str = "",
    reference_id: str = "",
    exception_type: str = "",
    where_path: str = "",
    search: str = "",
) -> List[model.AppErrorEvent]:
    if not app_error_event_table_available():
        return []

    query = model.AppErrorEvent.query

    actor_token = (actor or "").strip()
    if actor_token != "":
        query = query.filter(model.AppErrorEvent.actor.ilike(f"%{actor_token}%"))

    reference_token = (reference_id or "").strip()
    if reference_token != "":
        query = query.filter(
            model.AppErrorEvent.reference_id.ilike(f"%{reference_token}%")
        )

    exception_token = (exception_type or "").strip()
    if exception_token != "":
        query = query.filter(
            model.AppErrorEvent.exception_type.ilike(f"%{exception_token}%")
        )

    where_token = (where_path or "").strip()
    if where_token != "":
        query = query.filter(model.AppErrorEvent.where_path.ilike(f"%{where_token}%"))

    search_token = (search or "").strip()
    if search_token != "":
        search_like = f"%{search_token}%"
        query = query.filter(
            or_(
                model.AppErrorEvent.reference_id.ilike(search_like),
                model.AppErrorEvent.actor.ilike(search_like),
                model.AppErrorEvent.where_path.ilike(search_like),
                model.AppErrorEvent.endpoint.ilike(search_like),
                model.AppErrorEvent.exception_type.ilike(search_like),
                model.AppErrorEvent.exception_message.ilike(search_like),
                model.AppErrorEvent.fingerprint.ilike(search_like),
            )
        )

    return (
        query.order_by(
            model.AppErrorEvent.occurred_at.desc(),
            model.AppErrorEvent.id.desc(),
        )
        .limit(max(1, int(limit)))
        .all()
    )


def app_error_event_payload(row: model.AppErrorEvent) -> Dict[str, Any]:
    occurred_at = row.occurred_at
    when = ""
    if occurred_at is not None:
        when = (
            occurred_at.isoformat()
            if hasattr(occurred_at, "isoformat")
            else str(occurred_at)
        )

    request_context = row.request_context
    if not isinstance(request_context, dict):
        request_context = {}

    return {
        "id": row.id,
        "when": when,
        "reference_id": row.reference_id,
        "actor": row.actor,
        "ip": row.ip or "",
        "user_agent": row.user_agent or "",
        "method": row.method or "",
        "where": row.where_path or "",
        "endpoint": row.endpoint or "",
        "status_code": int(row.status_code or 500),
        "exception_type": row.exception_type or "",
        "message": row.exception_message or "",
        "fingerprint": row.fingerprint or "",
        "request_context": request_context,
        "stack_trace": row.stack_trace or "",
    }


__all__ = [
    "APP_ERROR_EVENT_DEFAULT_LIMIT",
    "APP_ERROR_EVENT_MAX_LIMIT",
    "APP_ERROR_EVENT_RETENTION_DAYS",
    "app_error_event_payload",
    "app_error_event_rows",
    "app_error_event_table_available",
    "record_app_error_event",
]
