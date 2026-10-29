from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set

from flask import g, request

import scheduler.logic.rbac_audit_support as audit_logic

from ._rbac_mutation_shared import _rbac_audit_preview, _RBACConflictError


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


def _record_rbac_action(
    action: str,
    where: str,
    how: str,
    what: str,
    *,
    source_ip: Optional[str] = None,
) -> None:
    actor = g.user.id if g.user is not None else "unknown"
    client_ip = source_ip or _request_client_ip()
    try:
        audit_logic.log_rbac_audit_event(
            action=action,
            actor=actor,
            where=where,
            how=how,
            what=what,
            source_ip=client_ip,
        )
    except TypeError:
        audit_logic.log_rbac_audit_event(
            action=action,
            actor=actor,
            where=where,
            how=how,
            what=what,
        )


def _rbac_actor_managed_groups(actor: Dict[str, Any]) -> Set[str]:
    groups = actor.get("managed_groups", set())
    if isinstance(groups, set):
        return groups
    return set()


def _rbac_badge(value: bool) -> str:
    return "yes" if value else "no"


def _rbac_state(value: bool) -> str:
    return "active" if value else "inactive"


def _rbac_assert_expected_bool_field(
    validated: Dict[str, Any],
    *,
    has_key: str,
    expected_key: str,
    current_value: bool,
    entity_label: str,
    entity_id: str,
    field_label: str,
) -> None:
    if not bool(validated.get(has_key)):
        return
    expected_value = bool(validated.get(expected_key))
    if current_value != expected_value:
        raise _RBACConflictError(
            f"{entity_label} changed before apply for "
            f"{entity_id} field {field_label}: "
            f"expected {_rbac_badge(expected_value)}, "
            f"current {_rbac_badge(current_value)}"
        )


def _rbac_assert_expected_text_field(
    validated: Dict[str, Any],
    *,
    has_key: str,
    expected_key: str,
    current_value: Any,
    entity_label: str,
    entity_id: str,
    field_label: str,
    formatter: Callable[[Any], str] = _rbac_audit_preview,
) -> None:
    if not bool(validated.get(has_key)):
        return
    expected_value = validated.get(expected_key, "")
    if current_value != expected_value:
        raise _RBACConflictError(
            f"{entity_label} changed before apply for "
            f"{entity_id} field {field_label}: "
            f"expected {formatter(expected_value)}, "
            f"current {formatter(current_value)}"
        )


def _rbac_apply_text_update(
    changes: List[str],
    obj: Any,
    *,
    attr: str,
    field_label: str,
    validated: Dict[str, Any],
    set_key: str,
    value_key: str,
    transform: Optional[Callable[[Any], Any]] = None,
    formatter: Callable[[Any], str] = _rbac_audit_preview,
) -> None:
    if not bool(validated.get(set_key)):
        return
    next_value = validated[value_key]
    if transform is not None:
        next_value = transform(next_value)
    current_value = getattr(obj, attr)
    if current_value == next_value:
        return
    changes.append(f"{field_label}={formatter(current_value)}->{formatter(next_value)}")
    setattr(obj, attr, next_value)


def _rbac_apply_bool_update(
    changes: List[str],
    obj: Any,
    *,
    attr: str,
    field_label: str,
    validated: Dict[str, Any],
    set_key: str,
    value_key: str,
) -> None:
    if not bool(validated.get(set_key)):
        return
    next_value = bool(validated[value_key])
    current_value = bool(getattr(obj, attr))
    if current_value == next_value:
        return
    changes.append(
        f"{field_label}={_rbac_badge(current_value)}->{_rbac_badge(next_value)}"
    )
    setattr(obj, attr, next_value)
