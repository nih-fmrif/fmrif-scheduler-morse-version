from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from scheduler import model
from scheduler.config import settings

logger = logging.getLogger(__name__)

_STARTUP_CHECK_SQL = text(
    """
    SELECT
      current_database() AS database_name,
      current_user AS database_user,
      current_setting('application_name', true) AS application_name,
      current_setting('statement_timeout') AS statement_timeout,
      current_setting('lock_timeout') AS lock_timeout,
      current_setting('idle_in_transaction_session_timeout')
        AS idle_in_transaction_session_timeout
    """
)

_DB_HEALTH_SQL = text(
    """
    SELECT
      current_database() AS database_name,
      current_setting('application_name', true) AS application_name,
      to_char(timezone('UTC', now()), 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS server_time_utc,
      (
        SELECT count(*)
        FROM pg_stat_activity
        WHERE datname = current_database()
      ) AS active_connection_count,
      (
        SELECT count(*)
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND wait_event_type = 'Lock'
      ) AS lock_wait_count,
      (
        SELECT count(*)
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND state = 'idle in transaction'
      ) AS idle_in_transaction_count
    """
)


def _compact_sql(statement: str, *, limit: int = 240) -> str:
    compacted = " ".join((statement or "").split())
    if len(compacted) <= limit:
        return compacted
    return f"{compacted[: limit - 3]}..."


def _session_bind() -> Engine | Connection:
    return model.db.session.get_bind()


def _execute_single_mapping(statement) -> dict[str, Any]:
    bind = _session_bind()
    if isinstance(bind, Connection):
        return dict(bind.execute(statement).mappings().one())
    with bind.connect() as connection:
        return dict(connection.execute(statement).mappings().one())


def configure_engine_runtime(engine: Engine) -> None:
    if getattr(engine, "_fmrif_runtime_configured", False):
        return

    threshold_ms = settings.database.slow_query_threshold_ms
    if threshold_ms > 0:

        @event.listens_for(engine, "before_cursor_execute")
        def _before_cursor_execute(
            conn: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            del conn, cursor, parameters, executemany
            context._fmrif_query_started_at = time.perf_counter()
            context._fmrif_query_statement = statement

        @event.listens_for(engine, "after_cursor_execute")
        def _after_cursor_execute(
            conn: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            del conn, cursor, parameters, executemany, statement
            started_at = getattr(context, "_fmrif_query_started_at", None)
            if started_at is None:
                return
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            if elapsed_ms < threshold_ms:
                return
            logger.warning(
                "Slow DB query: %.1fms sql=%s",
                elapsed_ms,
                _compact_sql(getattr(context, "_fmrif_query_statement", "")),
            )

    engine._fmrif_runtime_configured = True


def probe_database_health() -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        row = _execute_single_mapping(_DB_HEALTH_SQL)
    except SQLAlchemyError as exc:
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        return {
            "status": "error",
            "latency_ms": round(latency_ms, 1),
            "error": str(exc.__class__.__name__),
            "detail": str(exc),
        }

    latency_ms = (time.perf_counter() - started_at) * 1000.0
    return {
        "status": "ok",
        "latency_ms": round(latency_ms, 1),
        "database_name": row["database_name"],
        "application_name": row["application_name"],
        "server_time_utc": row["server_time_utc"],
        "active_connection_count": int(row["active_connection_count"] or 0),
        "lock_wait_count": int(row["lock_wait_count"] or 0),
        "idle_in_transaction_count": int(row["idle_in_transaction_count"] or 0),
    }


def verify_startup_database_connectivity() -> None:
    try:
        row = _execute_single_mapping(_STARTUP_CHECK_SQL)
    except SQLAlchemyError as exc:
        raise RuntimeError(
            f"Database startup check failed: {exc.__class__.__name__} {exc}".strip()
        ) from exc

    logger.info(
        "Database startup check passed: database=%s application_name=%s "
        "statement_timeout=%s lock_timeout=%s "
        "idle_in_transaction_session_timeout=%s",
        row["database_name"],
        row["application_name"],
        row["statement_timeout"],
        row["lock_timeout"],
        row["idle_in_transaction_session_timeout"],
    )


def dispose_database_engines() -> None:
    model.db.session.remove()
    seen_bind_ids: set[int] = set()
    for bind in list(model.db.engines.values()):
        bind_id = id(bind)
        if bind_id in seen_bind_ids:
            continue
        seen_bind_ids.add(bind_id)
        dispose = getattr(bind, "dispose", None)
        if callable(dispose):
            dispose()
