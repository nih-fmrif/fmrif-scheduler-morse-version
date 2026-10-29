from __future__ import annotations

import datetime
import re
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from flask import abort, current_app, request
from sqlalchemy.exc import SQLAlchemyError

import scheduler.logic.schedule_editor as logic
from scheduler import model
from scheduler.scheduler_save_error_attribution import build_scheduler_diff_context
from scheduler.scheduler_save_error_policy import explain_scheduler_save_error

BreadcrumbLinks = Dict[str, List[Tuple[str, str]]]
SubpageLinks = Dict[str, Dict[str, Union[str, List[Tuple[str, str]]]]]

_my_url_fn: Optional[Callable[[], str]] = None
_to_fn: Optional[Callable[..., Any]] = None
_breadcrumb_fn: Optional[Callable[..., BreadcrumbLinks]] = None
_subpage_nav_fn: Optional[
    Callable[[str, List[Tuple[bool, str, str]]], SubpageLinks]
] = None
_SYNTHETIC_SLOT_ID = re.compile(r"^new-(\d{4}-\d{2}-\d{2})-(\d{1,2})$")
DB_CLOCK_WARNING = "Database time unavailable. Unable to refresh ET date right now."


class SlotSaveNormalizationError(Exception):
    def __init__(self, slot_id: str, source: str, code: str, message: str):
        super().__init__(message)
        self.slot_id = slot_id
        self.source = source
        self.code = code
        self.message = message


def configure_route_helpers(
    *,
    my_url_fn: Callable[[], str],
    to_fn: Callable[..., Any],
    breadcrumb_fn: Callable[..., BreadcrumbLinks],
    subpage_nav_fn: Callable[[str, List[Tuple[bool, str, str]]], SubpageLinks],
) -> None:
    global _my_url_fn, _to_fn, _breadcrumb_fn, _subpage_nav_fn
    _my_url_fn = my_url_fn
    _to_fn = to_fn
    _breadcrumb_fn = breadcrumb_fn
    _subpage_nav_fn = subpage_nav_fn


def _require_helper(
    helper: Optional[Callable[..., Any]], name: str
) -> Callable[..., Any]:
    if helper is None:
        raise RuntimeError(f"Route helper not configured: {name}")
    return helper


def my_url() -> str:
    return _require_helper(_my_url_fn, "my_url")()


def to(page: str, **kwargs: Any) -> Any:
    return _require_helper(_to_fn, "to")(page, **kwargs)


def breadcrumb(*routes: Union[str, Tuple[str, str]]) -> BreadcrumbLinks:
    return _require_helper(_breadcrumb_fn, "breadcrumb")(*routes)


def subpage_nav(title: str, links: List[Tuple[bool, str, str]]) -> SubpageLinks:
    return _require_helper(_subpage_nav_fn, "subpage_nav")(title, links)


def _db_clock_date() -> Tuple[Optional[datetime.date], Optional[str]]:
    try:
        return logic.db_now()[0], None
    except SQLAlchemyError:
        current_app.logger.exception(
            "unable to resolve DB ET clock for scheduler date defaults"
        )
        return None, DB_CLOCK_WARNING


def schedule_window_from_request(device: Optional[model.Device] = None) -> tuple:
    _ = device
    date = None
    the_date = request.args.get("start")
    if the_date is not None:
        date = logic.parse_date(the_date)
        if date is None:
            abort(400, f"invalid start: {the_date} (must be YYYY-MM-DD date)")
    clock_warning = None
    if date is None:
        date, clock_warning = _db_clock_date()
    if date is None:
        abort(503, DB_CLOCK_WARNING)

    days = 7
    the_days = request.args.get("days")
    if the_days is not None:
        days = logic.parse_days(the_days)
        if days is None:
            abort(400, f"invalid days: {the_days} (must be in 1-31)")

    end_date = logic.end_date(date, days - 1)

    return date, days, end_date, clock_warning


def _slot_stub(day, hour: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"new-{logic.fmt_date(day)}-{hour:02d}",
        hour=hour,
        date=day,
        group="",
        user="",
        requests=[],
        error=False,
        template=None,
        used=None,
        errors=[],
    )


def _db_weekday_for(date_value) -> int:
    return int(date_value.isoweekday()) % 7


def _slot_error_row(
    source: str, code: str, message: str, blocking: bool = True
) -> Dict[str, Union[str, bool]]:
    return {
        "source": source,
        "code": code,
        "message": message,
        "blocking": blocking,
        "origin": "server",
    }


def _log_scheduler_save_database_error(
    err: SQLAlchemyError, *, phase: str
) -> Dict[str, Union[str, bool]]:
    decision = explain_scheduler_save_error(err)
    logger = current_app.logger if current_app else None
    if logger:
        if decision.notify_admin:
            logger.exception(
                "Scheduler save %s hit an unmapped database error policy path",
                phase,
            )
        else:
            logger.warning(
                "Scheduler save %s rejected by approved database policy "
                "(code=%s, source=%s)",
                phase,
                decision.code,
                decision.source,
            )
    return _slot_error_row(
        decision.source,
        decision.code,
        decision.message,
        blocking=True,
    )


def _map_server_errors_to_client_ids(errors, synthetic_map):
    mapped_errors = {}
    for entry_id, rows in errors.items():
        key = synthetic_map.get(str(entry_id), str(entry_id))
        mapped_errors[key] = rows
    return mapped_errors


def _build_error_map_for_client_ids(client_ids, row):
    mapped = {}
    for client_id in client_ids:
        key = str(client_id)
        mapped.setdefault(key, []).append(dict(row))
    if len(mapped) == 0:
        mapped["slot"] = [dict(row)]
    return mapped


def _normalize_schedule_diffs_for_save(diffs, entries, device, user):
    by_slot = {(entry.date, int(entry.hour)): entry for entry in entries}
    normalized = []
    server_to_client = {}
    diff_contexts = {}
    for raw in diffs:
        diff = dict(raw)
        raw_id = diff.get("id")
        client_id = str(raw_id)
        if isinstance(raw_id, str):
            match = _SYNTHETIC_SLOT_ID.fullmatch(raw_id.strip())
            if match is not None:
                slot_date = logic.parse_date(match.group(1))
                slot_hour = int(match.group(2))
                if diff.get("date") is not None:
                    parsed = logic.parse_date(str(diff.get("date")))
                    if parsed is not None:
                        slot_date = parsed
                if diff.get("hour") is not None:
                    try:
                        slot_hour = int(diff.get("hour"))
                    except (TypeError, ValueError):
                        raise SlotSaveNormalizationError(
                            raw_id,
                            "hour",
                            "invalid_hour",
                            f"invalid hour for synthetic slot id: {raw_id}",
                        )
                if slot_date is None or slot_hour < 0 or slot_hour > 23:
                    raise SlotSaveNormalizationError(
                        raw_id,
                        "slot",
                        "invalid_slot",
                        f"invalid synthetic slot id: {raw_id}",
                    )
                slot = (slot_date, slot_hour)
                entry = by_slot.get(slot)
                if entry is None:
                    entry = model.ScheduleEntry()
                    entry.device = device.id
                    entry.date = slot_date
                    entry.dow = _db_weekday_for(slot_date)
                    entry.hour = slot_hour
                    entry.group = None
                    entry.user = None
                    entry.orig_group = None
                    entry.orig_inst = None
                    entry.template = None
                    entry.used = None
                    entry.modified_by = user.id
                    model.db.session.add(entry)
                    try:
                        model.db.session.flush()
                    except SQLAlchemyError as err:
                        row = _log_scheduler_save_database_error(
                            err, phase="synthetic slot normalization"
                        )
                        raise SlotSaveNormalizationError(
                            raw_id,
                            str(row["source"]),
                            str(row["code"]),
                            str(row["message"]),
                        ) from err
                    entries.append(entry)
                    by_slot[slot] = entry
                diff["id"] = entry.id
                server_to_client[str(entry.id)] = raw_id
        server_ref = f"d{len(normalized)}"
        diff["_server_ref"] = server_ref
        diff_contexts[server_ref] = build_scheduler_diff_context(
            server_ref, client_id, diff
        )
        normalized.append(diff)
    return normalized, server_to_client, diff_contexts
