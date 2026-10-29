"""Session-local helpers for auth-test role overlays."""

from typing import Iterable, List, Optional, Set

from flask import session

_AUTH_TEST_PI_GROUPS_KEY = "auth_test_pi_groups"


def _normalize_group_ids(raw_groups: Iterable[object]) -> List[str]:
    groups: List[str] = []
    for raw_group in raw_groups:
        group_id = str(raw_group or "").strip()
        if not group_id:
            continue
        if group_id not in groups:
            groups.append(group_id)
    return groups


def _session_user_id() -> str:
    try:
        return str(session.get("user_name") or "").strip()
    except RuntimeError:
        return ""


def _target_user_id(user: Optional[object]) -> str:
    if user is None:
        return ""
    if isinstance(user, str):
        return user.strip()
    return str(getattr(user, "id", "") or getattr(user, "username", "") or "").strip()


def get_auth_test_session_pi_groups(user: Optional[object]) -> Set[str]:
    session_user = _session_user_id()
    if session_user == "":
        return set()

    target_user = _target_user_id(user)
    if target_user != "" and target_user != session_user:
        return set()

    try:
        raw_groups = session.get(_AUTH_TEST_PI_GROUPS_KEY, [])
    except RuntimeError:
        return set()

    if not isinstance(raw_groups, list):
        return set()
    return set(_normalize_group_ids(raw_groups))


def has_auth_test_session_pi_group(user: Optional[object], group_id: str) -> bool:
    target_group = str(group_id or "").strip()
    if target_group == "":
        return False
    return target_group in get_auth_test_session_pi_groups(user)


def set_auth_test_session_pi_groups(user_id: str, group_ids: Iterable[object]) -> None:
    session_user = _session_user_id()
    target_user = _target_user_id(user_id)
    if session_user == "" or target_user == "" or session_user != target_user:
        return

    normalized_groups = _normalize_group_ids(group_ids)
    if normalized_groups:
        session[_AUTH_TEST_PI_GROUPS_KEY] = normalized_groups
    else:
        session.pop(_AUTH_TEST_PI_GROUPS_KEY, None)
    session.modified = True


def merge_auth_test_session_pi_groups(
    user_id: str, group_ids: Iterable[object]
) -> None:
    session_groups = list(get_auth_test_session_pi_groups(user_id))
    session_groups.extend(group_ids)
    set_auth_test_session_pi_groups(user_id, session_groups)


def clear_auth_test_session_pi_groups() -> None:
    try:
        session.pop(_AUTH_TEST_PI_GROUPS_KEY, None)
        session.modified = True
    except RuntimeError:
        return
