from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping

_CSRF_TOKEN_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"', re.IGNORECASE)
_DATALIST_RE = re.compile(
    r'<datalist[^>]*id="(?P<id>[^"]+)"[^>]*>(?P<body>.*?)</datalist>',
    re.IGNORECASE | re.DOTALL,
)
_OPTION_VALUE_RE = re.compile(r'<option\b[^>]*value="([^"]*)"', re.IGNORECASE)


@dataclass(frozen=True)
class Assignment:
    group: str
    member: str


def extract_csrf_token(html_text: str) -> str | None:
    match = _CSRF_TOKEN_RE.search(html_text)
    if match is None:
        return None
    return html.unescape(match.group(1))


def extract_datalist_options(html_text: str) -> dict[str, list[str]]:
    datalists: dict[str, list[str]] = {}
    for match in _DATALIST_RE.finditer(html_text):
        datalist_id = html.unescape(match.group("id"))
        body = match.group("body")
        values = [
            html.unescape(value).strip()
            for value in _OPTION_VALUE_RE.findall(body)
            if html.unescape(value).strip()
        ]
        datalists[datalist_id] = values
    return datalists


def extract_first_assignment(html_text: str) -> Assignment | None:
    datalists = extract_datalist_options(html_text)
    for group in datalists.get("groups", []):
        members = datalists.get(f"members-of-{group}", [])
        if members:
            return Assignment(group=group, member=members[0])
    return None


def jump_day(start: str, delta_days: int) -> str:
    return (date.fromisoformat(start) + timedelta(days=delta_days)).isoformat()


def synthetic_slot_id(slot_date: str, hour: int) -> str:
    return f"new-{slot_date}-{hour:02d}"


def classify_scheduler_save(payload: Mapping[str, Any], slot_id: str) -> str:
    saved = payload.get("saved")
    if isinstance(saved, int) and saved > 0:
        return "saved"

    errors = payload.get("errors")
    if not isinstance(errors, Mapping):
        return "noop"

    slot_errors = errors.get(slot_id)
    if not isinstance(slot_errors, list) or len(slot_errors) == 0:
        return "noop"

    if all(
        isinstance(error, Mapping)
        and (error.get("code") == "slot_conflict" or error.get("type") == "overwrote")
        for error in slot_errors
    ):
        return "conflict"

    return "error"
