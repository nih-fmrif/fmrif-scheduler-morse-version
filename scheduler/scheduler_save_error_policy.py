from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

MAX_CLIENT_DB_DETAIL_CHARS = 220


@dataclass(frozen=True)
class SchedulerSaveErrorPolicyDecision:
    source: str
    code: str
    message: str
    notify_admin: bool = False


@dataclass(frozen=True)
class _ConstraintPolicy:
    source: str
    code: str
    message: str


_CONSTRAINT_POLICIES = {
    "tblsched_scannercode_key": _ConstraintPolicy(
        source="slot",
        code="slot_conflict",
        message=(
            "another entry already exists for this device, date, and hour. "
            "refresh the schedule and retry."
        ),
    ),
    "tblsched_deptcode_fkey": _ConstraintPolicy(
        source="group",
        code="invalid_group",
        message="selected group is no longer valid. choose a different group and retry.",
    ),
    "tblsched_orig_deptcode_fkey": _ConstraintPolicy(
        source="group",
        code="invalid_group",
        message="selected group is no longer valid. choose a different group and retry.",
    ),
    "tblsched_researchercode_fkey": _ConstraintPolicy(
        source="member",
        code="invalid_member",
        message=(
            "selected member is no longer valid for this slot. choose a different "
            "member and retry."
        ),
    ),
    "tblsched_instcode_fkey": _ConstraintPolicy(
        source="institute",
        code="invalid_institute",
        message="selected institute is no longer valid. choose a different institute and retry.",
    ),
    "tblsched_orig_inst_fkey": _ConstraintPolicy(
        source="institute",
        code="invalid_institute",
        message="selected institute is no longer valid. choose a different institute and retry.",
    ),
    "tblsched_scanner_fkey": _ConstraintPolicy(
        source="device",
        code="invalid_device",
        message="device is no longer available. refresh the schedule and retry.",
    ),
    "tblsched_templateid_fkey": _ConstraintPolicy(
        source="template",
        code="invalid_template",
        message="selected template is no longer valid. refresh the schedule and retry.",
    ),
    "tblsched_scheddow": _ConstraintPolicy(
        source="slot",
        code="invalid_slot",
        message="slot weekday no longer matches the selected date. refresh the schedule and retry.",
    ),
    "tblsched_schedhour": _ConstraintPolicy(
        source="slot",
        code="invalid_slot",
        message="slot hour is outside the allowed range. refresh the schedule and retry.",
    ),
}


def _compact_detail(
    primary: Optional[str],
    detail: Optional[str],
    constraint: Optional[str],
) -> str:
    chunks = []
    if constraint:
        chunks.append(str(constraint).strip())
    if primary:
        chunks.append(str(primary).strip())
    if detail:
        chunks.append(str(detail).strip())
    text = ": ".join(chunk for chunk in chunks if chunk)
    if len(text) <= MAX_CLIENT_DB_DETAIL_CHARS:
        return text
    return f"{text[: MAX_CLIENT_DB_DETAIL_CHARS - 3].rstrip()}..."


def _decision_from_sqlstate(
    sqlstate: Optional[str],
    constraint: Optional[str],
    primary: Optional[str],
    detail: Optional[str],
) -> Optional[SchedulerSaveErrorPolicyDecision]:
    if sqlstate == "23505":
        return SchedulerSaveErrorPolicyDecision(
            source="slot",
            code="slot_conflict",
            message=(
                "another entry already exists for this device, date, and hour. "
                "refresh the schedule and retry."
            ),
            notify_admin=constraint is None,
        )
    if sqlstate == "23503":
        return SchedulerSaveErrorPolicyDecision(
            source="database",
            code="foreign_key_rejected",
            message=(
                "one of the selected records no longer exists. refresh the schedule "
                "and retry."
            ),
            notify_admin=constraint is None,
        )
    if sqlstate == "23514":
        return SchedulerSaveErrorPolicyDecision(
            source="slot",
            code="invalid_slot",
            message="the submitted slot values were rejected by the database. refresh and retry.",
            notify_admin=constraint is None,
        )
    if sqlstate == "23502":
        return SchedulerSaveErrorPolicyDecision(
            source="slot",
            code="missing_required_value",
            message="the save is missing a required slot value. review the edited slot and retry.",
            notify_admin=True,
        )
    return None


def explain_scheduler_save_error(
    err: SQLAlchemyError,
) -> SchedulerSaveErrorPolicyDecision:
    orig = getattr(err, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint = getattr(diag, "constraint_name", None)
    primary = getattr(diag, "message_primary", None)
    detail = getattr(diag, "message_detail", None)
    sqlstate = getattr(orig, "pgcode", None) or getattr(diag, "sqlstate", None)

    if constraint in _CONSTRAINT_POLICIES:
        policy = _CONSTRAINT_POLICIES[constraint]
        return SchedulerSaveErrorPolicyDecision(
            source=policy.source,
            code=policy.code,
            message=policy.message,
        )

    fallback = _decision_from_sqlstate(sqlstate, constraint, primary, detail)
    if fallback is not None:
        return fallback

    message = _compact_detail(primary, detail, constraint)
    if message:
        return SchedulerSaveErrorPolicyDecision(
            source="database",
            code="database_rejected",
            message=f"database rejected the change: {message}",
            notify_admin=True,
        )

    text = str(orig or err).splitlines()[0].strip()
    if text:
        if len(text) > MAX_CLIENT_DB_DETAIL_CHARS:
            text = f"{text[: MAX_CLIENT_DB_DETAIL_CHARS - 3].rstrip()}..."
        return SchedulerSaveErrorPolicyDecision(
            source="database",
            code="database_rejected",
            message=f"database rejected the change: {text}",
            notify_admin=True,
        )

    return SchedulerSaveErrorPolicyDecision(
        source="database",
        code="database_rejected",
        message="database rejected the change. review the edited slot and retry.",
        notify_admin=True,
    )
