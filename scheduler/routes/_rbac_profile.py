from __future__ import annotations

from time import perf_counter
from typing import Any, Dict, Optional

from flask import current_app, g, has_request_context, request
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import InvalidRequestError

_RBAC_PROFILE_PATHS = frozenset(
    {
        "/rbac",
        "/json/v1/rbac/explorer",
        "/json/v1/rbac/audit",
        "/json/v1/email/audit",
    }
)


def _rbac_profile_requested() -> bool:
    token = request.args.get("profile", "").strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    header = request.headers.get("X-RBAC-Profile", "").strip().lower()
    return header in {"1", "true", "yes", "on"}


def _rbac_profile_should_trace_request() -> bool:
    return request.path in _RBAC_PROFILE_PATHS and _rbac_profile_requested()


def _rbac_profile_payload_bytes(response) -> int:
    payload_size = response.calculate_content_length()
    if payload_size is not None:
        return int(payload_size)
    return len(response.get_data(cache=True))


def _rbac_profile_start_request() -> None:
    if not _rbac_profile_should_trace_request():
        return

    state: Dict[str, Any] = {
        "started_at": perf_counter(),
        "query_count": 0,
    }

    def _before_cursor_execute(
        _conn,
        _cursor,
        _statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if not has_request_context():
            return
        current_state = getattr(g, "_rbac_profile_state", None)
        if current_state is not state:
            return
        state["query_count"] = int(state["query_count"]) + 1

    event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
    state["listener"] = _before_cursor_execute
    g._rbac_profile_state = state


def _rbac_profile_cleanup_state() -> Optional[Dict[str, Any]]:
    state = getattr(g, "_rbac_profile_state", None)
    if not isinstance(state, dict):
        return None

    listener = state.get("listener")
    if listener is not None:
        try:
            event.remove(Engine, "before_cursor_execute", listener)
        except (InvalidRequestError, ValueError, TypeError):
            pass

    g._rbac_profile_state = None
    return state


def _rbac_profile_finish_request(response):
    state = _rbac_profile_cleanup_state()
    if state is None:
        return response

    duration_ms = max(0.0, (perf_counter() - float(state["started_at"])) * 1000.0)
    query_count = int(state.get("query_count", 0))
    payload_bytes = _rbac_profile_payload_bytes(response)

    response.headers["X-RBAC-Profile-Duration-Ms"] = f"{duration_ms:.2f}"
    response.headers["X-RBAC-Profile-SQL-Queries"] = str(query_count)
    response.headers["X-RBAC-Profile-Payload-Bytes"] = str(payload_bytes)

    current_app.logger.info(
        "RBAC profile path=%s endpoint=%s status=%s duration_ms=%.2f sql_queries=%d payload_bytes=%d",
        request.path,
        request.endpoint,
        response.status_code,
        duration_ms,
        query_count,
        payload_bytes,
    )
    return response


def register_rbac_profile_hooks(app) -> None:
    @app.before_request
    def _rbac_profile_before_request() -> None:
        _rbac_profile_start_request()

    @app.after_request
    def _rbac_profile_after_request(response):
        return _rbac_profile_finish_request(response)

    @app.teardown_request
    def _rbac_profile_teardown_request(_exc: Optional[BaseException]) -> None:
        _rbac_profile_cleanup_state()
