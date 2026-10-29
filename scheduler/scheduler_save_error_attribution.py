from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from sqlalchemy.exc import SQLAlchemyError

from scheduler.scheduler_save_error_policy import explain_scheduler_save_error

_DETAIL_KEY_VALUES = re.compile(r"Key \((?P<keys>[^)]+)\)=\((?P<values>[^)]+)\)")
_TRACKED_FIELDS = frozenset({"group", "member", "institute", "med", "train", "tech"})


@dataclass(frozen=True)
class SchedulerDiffContext:
    server_ref: str
    client_id: str
    server_id: int
    date: Optional[datetime.date]
    hour: Optional[int]
    changed_fields: frozenset[str]
    group_value: Optional[str]
    member_value: Optional[str]
    institute_value: Optional[str]


def _parse_iso_date(raw: object) -> Optional[datetime.date]:
    if isinstance(raw, datetime.date):
        return raw
    text = str(raw or "").strip()
    if text == "":
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def _parse_int(raw: object) -> Optional[int]:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _new_value(change: object) -> Optional[str]:
    if not isinstance(change, (list, tuple)) or len(change) < 2:
        return None
    value = str(change[1]).strip()
    return value or None


def build_scheduler_diff_context(
    server_ref: str, client_id: str, diff: Mapping[str, object]
) -> SchedulerDiffContext:
    return SchedulerDiffContext(
        server_ref=server_ref,
        client_id=str(client_id),
        server_id=int(diff["id"]),
        date=_parse_iso_date(diff.get("date")),
        hour=_parse_int(diff.get("hour")),
        changed_fields=frozenset(key for key in diff if key in _TRACKED_FIELDS),
        group_value=_new_value(diff.get("group")),
        member_value=_new_value(diff.get("member")),
        institute_value=_new_value(diff.get("institute")),
    )


def _unique_client_ids(contexts: Iterable[SchedulerDiffContext]) -> List[str]:
    seen = set()
    out: List[str] = []
    for context in contexts:
        if context.client_id in seen:
            continue
        seen.add(context.client_id)
        out.append(context.client_id)
    return out


def _extract_diagnostic_key_values(err: SQLAlchemyError) -> Dict[str, str]:
    orig = getattr(err, "orig", None)
    diag = getattr(orig, "diag", None)
    detail = getattr(diag, "message_detail", None)
    if not detail:
        return {}
    match = _DETAIL_KEY_VALUES.search(str(detail))
    if match is None:
        return {}
    keys = [key.strip().lower() for key in match.group("keys").split(",")]
    values = [value.strip() for value in match.group("values").split(",")]
    if len(keys) != len(values):
        return {}
    return dict(zip(keys, values))


def _match_slot_contexts(
    contexts: Sequence[SchedulerDiffContext], key_values: Mapping[str, str]
) -> List[SchedulerDiffContext]:
    slot_date = _parse_iso_date(key_values.get("scheddate"))
    slot_hour = _parse_int(key_values.get("schedhour"))
    if slot_date is None or slot_hour is None:
        return []
    return [
        context
        for context in contexts
        if context.date == slot_date and context.hour == slot_hour
    ]


def select_scheduler_error_client_ids(
    err: SQLAlchemyError,
    contexts_by_ref: Mapping[str, SchedulerDiffContext],
    *,
    candidate_refs: Optional[Sequence[str]] = None,
) -> List[str]:
    candidates = (
        [contexts_by_ref[ref] for ref in candidate_refs if ref in contexts_by_ref]
        if candidate_refs is not None
        else list(contexts_by_ref.values())
    )
    if len(candidates) <= 1:
        return _unique_client_ids(candidates)

    decision = explain_scheduler_save_error(err)
    key_values = _extract_diagnostic_key_values(err)

    matched: List[SchedulerDiffContext] = []
    if decision.source == "slot":
        matched = _match_slot_contexts(candidates, key_values)
    elif decision.source == "group":
        group_value = key_values.get("deptcode") or key_values.get("orig_deptcode")
        if group_value:
            matched = [
                context for context in candidates if context.group_value == group_value
            ]
    elif decision.source == "member":
        member_value = key_values.get("researchercode")
        if member_value:
            matched = [
                context
                for context in candidates
                if context.member_value == member_value
            ]
    elif decision.source == "institute":
        institute_value = key_values.get("instcode") or key_values.get("orig_instcode")
        if institute_value:
            matched = [
                context
                for context in candidates
                if context.institute_value == institute_value
            ]

    if matched:
        return _unique_client_ids(matched)

    if decision.source in {"group", "member", "institute"}:
        heuristic = [
            context
            for context in candidates
            if decision.source in context.changed_fields
        ]
        if heuristic:
            return _unique_client_ids(heuristic)

    return _unique_client_ids(candidates)
