from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

from flask import abort, url_for
from sqlalchemy.orm import Load, load_only

from scheduler import logic, model

_RBAC_SCOPE_LABELS: Dict[str, str] = {
    "group": "groups",
    "device": "devices",
    "user": "users",
}
_RBAC_AUDIT_SCOPE_LABELS: Dict[str, str] = {
    "all": "all",
    **_RBAC_SCOPE_LABELS,
}
_RBAC_EMAIL_STATUS_OPTIONS: List[Dict[str, str]] = [
    {"value": logic.EMAIL_STATUS_NONE, "label": logic.EMAIL_STATUS_NONE},
    {"value": logic.EMAIL_STATUS_SENT, "label": logic.EMAIL_STATUS_SENT},
    {"value": logic.EMAIL_STATUS_FAILED, "label": logic.EMAIL_STATUS_FAILED},
]
_RBAC_GRAPH_NODE_LIMIT = 12
_RBAC_TABLE_ROW_LIMIT = 250
_RBAC_MATRIX_ROW_LIMIT = 500


def _rbac_actor(user: Optional[model.User]) -> Dict[str, Any]:
    actor: Dict[str, Any] = {
        "id": user.id if user is not None else "",
        "is_admin": False,
        "is_dev_pi": False,
        "managed_groups": set(),
        "allowed_scopes": [],
        "can_access": False,
    }
    if user is None or not user.active:
        return actor

    is_admin = logic.is_admin(user)
    managed_groups: Set[str] = set()
    if not is_admin:
        M = model.Membership
        q = M.query.options(load_only(M.group))
        q = q.filter(M.user == user.id)
        q = q.filter(M.user_active)
        q = q.filter(M.approved)
        q = q.filter(M.pi)
        q = q.filter(M.group_active)
        managed_groups = {row.group for row in q.all()}
    else:
        managed_groups = {
            row.group
            for row in model.Membership.query.options(load_only(model.Membership.group))
            .filter(model.Membership.user == user.id)
            .filter(model.Membership.pi)
            .all()
        }

    is_dev_pi = "DEV" in managed_groups

    allowed_scopes: List[str] = []
    if is_admin:
        allowed_scopes = [scope for scope in _RBAC_SCOPE_LABELS.keys()]
    else:
        if len(managed_groups) > 0:
            allowed_scopes.append("group")
        if is_dev_pi:
            allowed_scopes.append("device")

    actor.update(
        {
            "is_admin": is_admin,
            "is_dev_pi": is_dev_pi,
            "managed_groups": managed_groups,
            "allowed_scopes": allowed_scopes,
            "can_access": bool(is_admin or len(managed_groups) > 0),
        }
    )
    return actor


def _rbac_actor_scope_labels(actor: Dict[str, Any]) -> Dict[str, str]:
    allowed = actor.get("allowed_scopes", [])
    if not isinstance(allowed, list) or len(allowed) == 0:
        return {}
    return {
        scope: _RBAC_SCOPE_LABELS[scope]
        for scope in allowed
        if scope in _RBAC_SCOPE_LABELS
    }


def _rbac_actor_allows_scope(actor: Dict[str, Any], scope: str) -> bool:
    allowed = actor.get("allowed_scopes", [])
    if not isinstance(allowed, list):
        return False
    return scope in allowed


def _rbac_actor_managed_groups(actor: Dict[str, Any]) -> Set[str]:
    groups = actor.get("managed_groups", set())
    if isinstance(groups, set):
        return groups
    return set()


def _rbac_href_allowed_for_actor(href: str, actor: Dict[str, Any]) -> bool:
    target = (href or "").strip()
    if target == "":
        return True
    parsed = urlparse(target)
    if parsed.path.rstrip("/") != "/rbac":
        return True
    scope = parse_qs(parsed.query).get("scope", ["group"])[0].strip().lower()
    if scope not in _RBAC_SCOPE_LABELS:
        return False
    return _rbac_actor_allows_scope(actor, scope)


def _rbac_badge(value: bool) -> str:
    return "yes" if value else "no"


def _rbac_state(value: bool) -> str:
    return "active" if value else "inactive"


def _rbac_email_status(value: str) -> str:
    token = (value or "").strip().lower()
    if token in logic.EMAIL_STATUS_VALUES:
        return token
    return logic.EMAIL_STATUS_NONE


def _rbac_device_label(device: model.Device) -> str:
    if device.label and device.label != device.id:
        return f"{device.label} ({device.id})"
    return device.id


def _rbac_group_label(group: model.Group) -> str:
    if group.label and group.label != group.id:
        return f"{group.label} ({group.id})"
    return group.id


def _rbac_user_label(user: model.User) -> str:
    if user.label and user.label != user.id:
        return f"{user.label} ({user.id})"
    return user.id


def _rbac_slice_graph_nodes(
    entries: List[Dict[str, str]],
    *,
    limit: int = _RBAC_GRAPH_NODE_LIMIT,
) -> Tuple[List[Dict[str, str]], int]:
    if len(entries) <= limit:
        return entries, 0
    return entries[:limit], len(entries) - limit


def _rbac_limit_rows(
    rows: List[Dict[str, Any]],
    *,
    limit: int = _RBAC_TABLE_ROW_LIMIT,
) -> Tuple[List[Dict[str, Any]], int]:
    if len(rows) <= limit:
        return rows, 0
    return rows[:limit], len(rows) - limit


def _rbac_scopes(*, allowed_scopes: Optional[List[str]] = None) -> List[Dict[str, str]]:
    if allowed_scopes is None:
        allowed_scopes = [scope for scope in _RBAC_SCOPE_LABELS.keys()]
    return [
        {"id": scope_id, "label": label}
        for scope_id, label in _RBAC_SCOPE_LABELS.items()
        if scope_id in allowed_scopes
    ]


def _rbac_entities(
    scope: str,
    *,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    if scope == "group":
        query = model.Group.query.options(
            load_only(model.Group.id, model.Group.label, model.Group.active)
        ).order_by(model.Group.label, model.Group.id)
        if not include_inactive:
            query = query.filter(model.Group.active)
        groups = query.all()
        return [
            {
                "id": group.id,
                "label": _rbac_group_label(group),
                "active": bool(group.active),
            }
            for group in groups
        ]

    if scope == "device":
        query = model.Device.query.options(
            load_only(model.Device.id, model.Device.label, model.Device.active)
        ).order_by(model.Device.label, model.Device.id)
        if not include_inactive:
            query = query.filter(model.Device.active)
        devices = query.all()
        return [
            {
                "id": device.id,
                "label": _rbac_device_label(device),
                "active": bool(device.active),
            }
            for device in devices
        ]

    if scope == "user":
        query = model.User.query.options(
            load_only(model.User.id, model.User.label, model.User.active)
        ).order_by(model.User.active.desc(), model.User.id)
        if not include_inactive:
            query = query.filter(model.User.active)
        users = query.all()
        return [
            {
                "id": user.id,
                "label": _rbac_user_label(user),
                "active": bool(user.active),
            }
            for user in users
        ]

    return []


def _rbac_entities_for_actor(
    scope: str,
    actor: Dict[str, Any],
    *,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    if not _rbac_actor_allows_scope(actor, scope):
        return []

    if bool(actor.get("is_admin")):
        return _rbac_entities(scope, include_inactive=include_inactive)

    if scope == "group":
        managed_groups = sorted(_rbac_actor_managed_groups(actor))
        if len(managed_groups) == 0:
            return []
        q = (
            model.Group.query.options(
                load_only(model.Group.id, model.Group.label, model.Group.active)
            )
            .filter(model.Group.id.in_(managed_groups))
            .order_by(model.Group.label, model.Group.id)
        )
        if not include_inactive:
            q = q.filter(model.Group.active)
        groups = q.all()
        return [
            {
                "id": group.id,
                "label": _rbac_group_label(group),
                "active": bool(group.active),
            }
            for group in groups
        ]

    if scope == "device":
        if not bool(actor.get("is_dev_pi")):
            return []
        q = model.Device.query.options(
            load_only(model.Device.id, model.Device.label, model.Device.active)
        ).order_by(model.Device.label, model.Device.id)
        if not include_inactive:
            q = q.filter(model.Device.active)
        devices = q.all()
        return [
            {
                "id": device.id,
                "label": _rbac_device_label(device),
                "active": bool(device.active),
            }
            for device in devices
        ]

    return []


def _rbac_entity_visible(scope: str, entity: str, *, include_inactive: bool) -> bool:
    if entity == "":
        return False
    if scope == "group":
        group = logic.get_group(entity)
        if group is None:
            return False
        return include_inactive or bool(group.active)
    if scope == "device":
        device = logic.get_device(entity)
        if device is None:
            return False
        return include_inactive or bool(device.active)
    if scope == "user":
        user = logic.get_user(entity)
        if user is None:
            return False
        return include_inactive or bool(user.active)
    return False


def _rbac_entity_visible_for_actor(
    scope: str,
    entity: str,
    actor: Dict[str, Any],
    *,
    include_inactive: bool,
) -> bool:
    if not _rbac_actor_allows_scope(actor, scope):
        return False
    if bool(actor.get("is_admin")):
        return _rbac_entity_visible(scope, entity, include_inactive=include_inactive)

    if scope == "group":
        if entity not in _rbac_actor_managed_groups(actor):
            return False
        group = logic.get_group(entity)
        if group is None:
            return False
        return include_inactive or bool(group.active)

    if scope == "device":
        if not bool(actor.get("is_dev_pi")):
            return False
        device = logic.get_device(entity)
        if device is None:
            return False
        return include_inactive or bool(device.active)

    return False


def _rbac_permission_flags(ud: model.UserDevice) -> str:
    flags = []
    if ud.templates:
        flags.append("templates")
    if ud.slot:
        flags.append("slot")
    if ud.tech:
        flags.append("tech")
    if ud.medical:
        flags.append("medical")
    if ud.training:
        flags.append("training")
    return ", ".join(flags) if flags else "none"


def _rbac_select_option(
    value: str,
    label: str,
    *,
    meta: str = "",
) -> Dict[str, str]:
    return {"value": value, "label": label, "meta": meta}


def _rbac_group_detail(
    group: model.Group,
    *,
    include_inactive: bool = False,
) -> Dict[str, Any]:
    memberships_query = (
        model.Membership.query.options(
            load_only(
                model.Membership.group,
                model.Membership.user,
                model.Membership.pi,
                model.Membership.approved,
                model.Membership.email_status,
                model.Membership.group_active,
                model.Membership.user_active,
            )
        )
        .filter(model.Membership.group == group.id)
        .order_by(model.Membership.user)
    )
    if not include_inactive:
        memberships_query = memberships_query.filter(model.Membership.user_active)
    memberships = memberships_query.all()
    devices_query = (
        model.Device.query.options(
            load_only(model.Device.id, model.Device.label, model.Device.active)
        )
        .join(model.DeviceGroup, model.DeviceGroup.device == model.Device.id)
        .filter(model.DeviceGroup.group == group.id)
        .order_by(model.Device.label, model.Device.id)
    )
    if not include_inactive:
        devices_query = devices_query.filter(model.Device.active)
    devices = devices_query.all()
    membership_by_user = {row.user: row for row in memberships}
    linked_device_ids = {device.id for device in devices}

    member_nodes: List[Dict[str, str]] = []
    member_rows: List[Dict[str, Any]] = []
    for row in memberships:
        status = "approved" if row.approved else "pending"
        tags = [status]
        if row.pi:
            tags.append("PI")
        if not row.user_active:
            tags.append("inactive user")
        if not row.group_active:
            tags.append("inactive group")
        meta = ", ".join(tags)
        member_nodes.append(
            {
                "label": row.user,
                "meta": meta,
                "href": url_for("rbac", scope="user", entity=row.user),
            }
        )
        member_rows.append(
            {
                "cells": {
                    "user": row.user,
                    "status": status,
                    "pi": _rbac_badge(bool(row.pi)),
                    "user_state": _rbac_state(bool(row.user_active)),
                },
                "actions": [
                    {
                        "label": "inspect user",
                        "href": url_for("rbac", scope="user", entity=row.user),
                    }
                ],
            }
        )

    device_nodes: List[Dict[str, str]] = []
    device_rows: List[Dict[str, Any]] = []
    for device in devices:
        device_nodes.append(
            {
                "label": _rbac_device_label(device),
                "meta": _rbac_state(bool(device.active)),
                "href": url_for("rbac", scope="device", entity=device.id),
            }
        )
        device_rows.append(
            {
                "cells": {
                    "device": _rbac_device_label(device),
                    "status": _rbac_state(bool(device.active)),
                },
                "actions": [
                    {
                        "label": "inspect device",
                        "href": url_for("rbac", scope="device", entity=device.id),
                    },
                ],
            }
        )

    all_devices_query = model.Device.query.options(
        load_only(model.Device.id, model.Device.label, model.Device.active)
    ).order_by(model.Device.label, model.Device.id)
    if not include_inactive:
        all_devices_query = all_devices_query.filter(model.Device.active)
    all_devices = all_devices_query.all()
    device_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for device in all_devices:
        linked = device.id in linked_device_ids
        can_link = bool(group.active) and (linked or bool(group.department))
        row = {
            "id": device.id,
            "search": (
                f"{device.id} {_rbac_device_label(device)} "
                f"{_rbac_state(bool(device.active))}"
            ),
            "cells": {
                "device": _rbac_device_label(device),
                "device_state": _rbac_state(bool(device.active)),
            },
            "values": {"linked": linked},
            "editable": {"linked": can_link},
            "operation": {
                "kind": "device.group.set",
                "group": group.id,
                "device": device.id,
            },
        }
        rank = (
            0 if linked else 1,
            0 if device.active else 1,
            (device.label or "").lower(),
            device.id.lower(),
        )
        device_matrix_rows_ranked.append((rank, row))
    device_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    device_matrix_rows = [row for _, row in device_matrix_rows_ranked]
    device_matrix_rows, device_matrix_more = _rbac_limit_rows(
        device_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )

    all_users_query = model.User.query.options(
        load_only(model.User.id, model.User.label, model.User.active)
    ).order_by(model.User.label, model.User.id)
    if not include_inactive:
        all_users_query = all_users_query.filter(model.User.active)
    all_users = all_users_query.all()
    current_pi_user = next((row.user for row in memberships if row.pi), "")
    eligible_pi_user_ids = sorted(
        {row.user for row in memberships if row.approved and row.user_active}
    )
    pi_option_ids = list(eligible_pi_user_ids)
    if current_pi_user != "" and current_pi_user not in pi_option_ids:
        pi_option_ids.append(current_pi_user)
    pi_options = []
    for user_id in pi_option_ids:
        label = user_id
        if user_id == current_pi_user and user_id not in eligible_pi_user_ids:
            label = f"{user_id} [current, not eligible]"
        pi_options.append({"value": user_id, "label": label})

    membership_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for user in all_users:
        membership = membership_by_user.get(user.id)
        if membership is None and not user.active:
            continue
        is_member = membership is not None
        approved = bool(membership.approved) if membership is not None else False
        pi = bool(membership.pi) if membership is not None else False
        email_status = (
            _rbac_email_status(membership.email_status)
            if membership is not None
            else logic.EMAIL_STATUS_NONE
        )
        status = "not member"
        if is_member:
            status = "approved" if approved else "pending"
        row = {
            "id": user.id,
            "search": (
                f"{user.id} {_rbac_user_label(user)} {status} "
                f"{_rbac_state(bool(user.active))} {email_status}"
            ),
            "cells": {
                "user": _rbac_user_label(user),
                "user_state": _rbac_state(bool(user.active)),
                "pi": _rbac_badge(pi),
            },
            "values": {
                "member": is_member,
                "approved": approved,
                "email_status": email_status,
            },
            "editable": {
                "member": bool(group.active and (user.active or is_member)),
                "approved": bool(group.active and user.active and is_member),
                "email_status": bool(group.active and is_member and not approved),
            },
            "operation": {
                "kind": "group.membership.set",
                "group": group.id,
                "user": user.id,
            },
        }
        rank = (
            0 if is_member else 1,
            0 if approved else 1,
            0 if user.active else 1,
            (user.label or "").lower(),
            user.id.lower(),
        )
        membership_matrix_rows_ranked.append((rank, row))
    membership_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    membership_matrix_rows = [row for _, row in membership_matrix_rows_ranked]
    membership_matrix_rows, membership_matrix_more = _rbac_limit_rows(
        membership_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )

    left_nodes, left_more = _rbac_slice_graph_nodes(member_nodes)
    right_nodes, right_more = _rbac_slice_graph_nodes(device_nodes)
    member_rows, member_more = _rbac_limit_rows(member_rows)
    device_rows, device_more = _rbac_limit_rows(device_rows)

    special_group = group.id in {"admin", "DEV"}
    can_toggle_active = not special_group
    status_note = "Edit group metadata, PI assignment, and active state in one row."
    if not can_toggle_active:
        status_note = "Special groups are always active and cannot be deactivated."
    institutes = (
        model.Inst.query.options(
            load_only(model.Inst.id, model.Inst.label, model.Inst.active)
        )
        .order_by(model.Inst.label, model.Inst.id)
        .all()
    )
    inst_options = [{"value": "", "label": "none"}]
    for inst in institutes:
        label = inst.label
        if label != inst.id:
            label = f"{inst.label} ({inst.id})"
        if not inst.active:
            label = f"{label} [inactive]"
        inst_options.append({"value": inst.id, "label": label})

    return {
        "summary": {
            "title": _rbac_group_label(group),
            "subtitle": "group",
            "badges": [
                _rbac_state(bool(group.active)),
                "membership-enabled" if group.has_membership else "membership-disabled",
                "joinable" if group.is_joinable else "not-joinable",
            ],
        },
        "links": [],
        "graph": {
            "source_title": "members",
            "target_title": "linked devices",
            "focus": {
                "label": _rbac_group_label(group),
                "href": "",
            },
            "sources": left_nodes,
            "targets": right_nodes,
            "source_more": left_more,
            "target_more": right_more,
        },
        "tables": [
            {
                "title": "members",
                "empty": "No members found for this group.",
                "more": member_more,
                "columns": [
                    {"key": "user", "label": "user"},
                    {"key": "status", "label": "status"},
                    {"key": "pi", "label": "pi"},
                    {"key": "user_state", "label": "user state"},
                ],
                "rows": member_rows,
            },
            {
                "title": "device links",
                "empty": "No devices linked to this group.",
                "more": device_more,
                "columns": [
                    {"key": "device", "label": "device"},
                    {"key": "status", "label": "device status"},
                ],
                "rows": device_rows,
            },
        ],
        "matrices": [
            {
                "id": "group-metadata-matrix",
                "title": "group settings",
                "description": status_note,
                "empty": "Group metadata unavailable.",
                "apply_label": "apply group settings",
                "confirm": f"Apply metadata updates for {group.id}?",
                "more": 0,
                "filter": False,
                "layout": "keyvalue",
                "rows": [
                    {
                        "id": f"{group.id}-label",
                        "search": f"{group.id} label {_rbac_group_label(group)}",
                        "label": "short label",
                        "kind": "input",
                        "input_type": "text",
                        "max_length": 20,
                        "field": "label",
                        "value": group.label or "",
                        "editable": True,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-description",
                        "search": f"{group.id} description {_rbac_group_label(group)}",
                        "label": "long label",
                        "kind": "input",
                        "input_type": "text",
                        "max_length": 75,
                        "field": "description",
                        "value": group.description or "",
                        "editable": True,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-addr",
                        "search": f"{group.id} email {_rbac_group_label(group)}",
                        "label": "email",
                        "kind": "input",
                        "input_type": "text",
                        "field": "addr",
                        "value": group.addr or "",
                        "editable": True,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-link",
                        "search": f"{group.id} link {_rbac_group_label(group)}",
                        "label": "link",
                        "kind": "input",
                        "input_type": "url",
                        "field": "link",
                        "value": group.link or "",
                        "editable": True,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-color",
                        "search": f"{group.id} color {_rbac_group_label(group)}",
                        "label": "legend color",
                        "kind": "input",
                        "input_type": "color",
                        "field": "color",
                        "value": group.color or "#000000",
                        "editable": not special_group,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-inst",
                        "search": f"{group.id} institute {_rbac_group_label(group)}",
                        "label": "institute",
                        "kind": "select",
                        "field": "inst",
                        "value": group.inst or "",
                        "options": inst_options,
                        "editable": not special_group,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-pi",
                        "search": f"{group.id} pi {_rbac_group_label(group)}",
                        "label": "PI user",
                        "kind": "select",
                        "field": "user",
                        "value": current_pi_user,
                        "options": pi_options,
                        "editable": bool(
                            group.active and len(eligible_pi_user_ids) > 0
                        ),
                        "operation": {
                            "kind": "group.pi.set",
                            "group": group.id,
                            "expected_current_pi": current_pi_user,
                        },
                    },
                    {
                        "id": f"{group.id}-active",
                        "search": f"{group.id} active {_rbac_group_label(group)}",
                        "label": "active",
                        "kind": "checkbox",
                        "field": "active",
                        "value": bool(group.active),
                        "editable": can_toggle_active,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-membership-enabled",
                        "search": f"{group.id} membership-enabled {_rbac_group_label(group)}",
                        "label": "membership-enabled",
                        "kind": "checkbox",
                        "value": bool(group.has_membership),
                        "editable": False,
                    },
                    {
                        "id": f"{group.id}-joinable",
                        "search": f"{group.id} joinable {_rbac_group_label(group)}",
                        "label": "joinable",
                        "kind": "checkbox",
                        "value": bool(group.is_joinable),
                        "editable": False,
                    },
                ],
            },
            {
                "id": "group-membership-matrix",
                "title": "membership state",
                "description": (
                    "Edit member and approval state. "
                    "PI assignment is managed in group settings."
                ),
                "empty": "No users found for this group.",
                "apply_label": "apply membership updates",
                "confirm": f"Apply membership updates for {group.id}?",
                "more": membership_matrix_more,
                "columns": [
                    {"key": "user", "label": "user", "kind": "text"},
                    {"key": "user_state", "label": "user state", "kind": "text"},
                    {"key": "member", "label": "member", "kind": "checkbox"},
                    {"key": "approved", "label": "approved", "kind": "checkbox"},
                    {
                        "key": "email_status",
                        "label": "email",
                        "kind": "select",
                        "options": _RBAC_EMAIL_STATUS_OPTIONS,
                    },
                    {"key": "pi", "label": "PI", "kind": "text"},
                ],
                "rows": membership_matrix_rows,
                "behavior": "group-membership",
            },
            {
                "id": "group-device-links-matrix",
                "title": "linked devices",
                "description": (
                    "Tick devices that should remain linked to this group."
                ),
                "empty": "No devices found.",
                "apply_label": "apply device links",
                "confirm": f"Apply device link updates for {group.id}?",
                "more": device_matrix_more,
                "columns": [
                    {"key": "device", "label": "device", "kind": "text"},
                    {
                        "key": "device_state",
                        "label": "device state",
                        "kind": "text",
                    },
                    {"key": "linked", "label": "linked", "kind": "checkbox"},
                ],
                "rows": device_matrix_rows,
            },
        ],
        "mutations": [],
    }


def _rbac_device_detail(
    device: model.Device,
    *,
    include_inactive: bool = False,
) -> Dict[str, Any]:
    groups_query = (
        model.Group.query.options(
            load_only(
                model.Group.id,
                model.Group.label,
                model.Group.active,
                model.Group.department,
            )
        )
        .join(model.DeviceGroup, model.DeviceGroup.group == model.Group.id)
        .filter(model.DeviceGroup.device == device.id)
        .order_by(model.Group.label, model.Group.id)
    )
    if not include_inactive:
        groups_query = groups_query.filter(model.Group.active)
    groups = groups_query.all()
    user_perms_query = (
        model.db.session.query(model.UserDevice, model.User)
        .join(model.User, model.User.id == model.UserDevice.user)
        .options(
            Load(model.UserDevice).load_only(
                model.UserDevice.user,
                model.UserDevice.device,
                model.UserDevice.templates,
                model.UserDevice.slot,
                model.UserDevice.tech,
                model.UserDevice.medical,
                model.UserDevice.training,
            ),
            Load(model.User).load_only(
                model.User.id, model.User.label, model.User.active
            ),
        )
        .filter(model.UserDevice.device == device.id)
        .order_by(model.User.id)
    )
    if not include_inactive:
        user_perms_query = user_perms_query.filter(model.User.active)
    user_perms = user_perms_query.all()

    source_nodes: List[Dict[str, str]] = []
    group_rows: List[Dict[str, Any]] = []
    for group in groups:
        source_nodes.append(
            {
                "label": _rbac_group_label(group),
                "meta": _rbac_state(bool(group.active)),
                "href": url_for("rbac", scope="group", entity=group.id),
            }
        )
        group_rows.append(
            {
                "cells": {
                    "group": _rbac_group_label(group),
                    "status": _rbac_state(bool(group.active)),
                },
                "actions": [
                    {
                        "label": "inspect group",
                        "href": url_for("rbac", scope="group", entity=group.id),
                    },
                ],
            }
        )

    target_nodes: List[Dict[str, str]] = []
    special_rows: List[Dict[str, Any]] = []
    for ud, user in user_perms:
        flags = _rbac_permission_flags(ud)
        target_nodes.append(
            {
                "label": _rbac_user_label(user),
                "meta": flags,
                "href": url_for("rbac", scope="user", entity=user.id),
            }
        )
        actions = [
            {
                "label": "inspect user",
                "href": url_for("rbac", scope="user", entity=user.id),
            }
        ]
        special_rows.append(
            {
                "cells": {
                    "user": _rbac_user_label(user),
                    "user_state": _rbac_state(bool(user.active)),
                    "permissions": flags,
                },
                "actions": actions,
            }
        )

    linked_group_ids = {group.id for group in groups}
    all_groups_query = model.Group.query.options(
        load_only(
            model.Group.id,
            model.Group.label,
            model.Group.active,
            model.Group.department,
        )
    ).order_by(model.Group.label, model.Group.id)
    if not include_inactive:
        all_groups_query = all_groups_query.filter(model.Group.active)
    all_groups = all_groups_query.all()
    group_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for group in all_groups:
        linked = group.id in linked_group_ids
        can_link = linked or (group.active and bool(group.department))
        row = {
            "id": group.id,
            "search": (
                f"{group.id} {_rbac_group_label(group)} "
                f"{_rbac_state(bool(group.active))}"
            ),
            "cells": {
                "group": _rbac_group_label(group),
                "group_state": _rbac_state(bool(group.active)),
            },
            "values": {"linked": linked},
            "editable": {"linked": bool(can_link)},
            "operation": {
                "kind": "device.group.set",
                "group": group.id,
                "device": device.id,
            },
        }
        rank = (
            0 if linked else 1,
            0 if group.active else 1,
            (group.label or "").lower(),
            group.id.lower(),
        )
        group_matrix_rows_ranked.append((rank, row))
    group_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    group_matrix_rows = [row for _, row in group_matrix_rows_ranked]
    group_matrix_rows, group_matrix_more = _rbac_limit_rows(
        group_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )

    dev_users_query = (
        model.User.query.options(
            load_only(model.User.id, model.User.label, model.User.active)
        )
        .join(model.Membership, model.Membership.user == model.User.id)
        .filter(model.Membership.group == "DEV")
        .filter(model.Membership.approved)
        .order_by(model.User.id)
    )
    if not include_inactive:
        dev_users_query = dev_users_query.filter(model.Membership.user_active).filter(
            model.User.active
        )
    dev_users = dev_users_query.all()
    dev_user_ids = {user.id for user in dev_users}
    tech_user_ids = {
        user_id
        for (user_id,) in model.Technologist.query.with_entities(
            model.Technologist.user
        )
        .filter(model.Technologist.approved_on.isnot(None))
        .all()
    }
    user_overrides = {ud.user: ud for ud, _ in user_perms}
    user_matrix_ids = sorted(set(dev_user_ids).union(set(user_overrides.keys())))
    users_by_id_query = model.User.query.options(
        load_only(model.User.id, model.User.label, model.User.active)
    ).filter(model.User.id.in_(user_matrix_ids))
    if not include_inactive:
        users_by_id_query = users_by_id_query.filter(model.User.active)
    users_by_id = {user.id: user for user in users_by_id_query.all()}
    user_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for user_id in user_matrix_ids:
        user = users_by_id.get(user_id)
        if user is None:
            continue
        override = user_overrides.get(user_id)
        dev_member = user_id in dev_user_ids
        is_technologist = user_id in tech_user_ids
        templates = bool(override.templates) if override is not None else False
        slot = bool(override.slot) if override is not None else False
        tech = bool(override.tech) if override is not None else False
        medical = bool(override.medical) if override is not None else False
        training = bool(override.training) if override is not None else False
        has_override = any((templates, slot, tech, medical, training))
        can_assign = bool(user.active and dev_member)
        row = {
            "id": user.id,
            "search": (
                f"{user.id} {_rbac_user_label(user)} "
                f"{'dev-member' if dev_member else 'non-dev'} "
                f"{'technologist' if is_technologist else 'non-technologist'}"
            ),
            "cells": {
                "user": _rbac_user_label(user),
                "user_state": _rbac_state(bool(user.active)),
                "dev_member": _rbac_badge(bool(dev_member)),
                "technologist": _rbac_badge(bool(is_technologist)),
            },
            "values": {
                "templates": templates,
                "slot": slot,
                "tech": tech,
                "medical": medical,
                "training": training,
            },
            "editable": {
                "templates": bool(can_assign or templates),
                "slot": bool(can_assign or slot),
                "tech": bool((can_assign and is_technologist) or tech),
                "medical": bool(can_assign or medical),
                "training": bool(can_assign or training),
            },
            "operation": {
                "kind": "user.device.set",
                "device": device.id,
                "user": user.id,
            },
        }
        rank = (
            0 if has_override else 1,
            0 if dev_member else 1,
            0 if user.active else 1,
            (user.label or "").lower(),
            user.id.lower(),
        )
        user_matrix_rows_ranked.append((rank, row))
    user_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    user_matrix_rows = [row for _, row in user_matrix_rows_ranked]
    user_matrix_rows, user_matrix_more = _rbac_limit_rows(
        user_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )
    quick_add_user_options = []
    for dev_user in sorted(dev_users, key=lambda row: row.id.lower()):
        if not dev_user.active:
            continue
        suffix = "technologist" if dev_user.id in tech_user_ids else "DEV member"
        quick_add_user_options.append(
            {
                "value": dev_user.id,
                "label": _rbac_user_label(dev_user),
                "meta": suffix,
            }
        )
    quick_add_config: Optional[Dict[str, Any]] = None
    if len(quick_add_user_options) > 0:
        quick_add_config = {
            "label": "+ add DEV user",
            "title": f"Add DEV user permissions for {device.id}",
            "submit_label": "add permissions",
            "scope": "device",
            "entity": device.id,
            "operation": {
                "kind": "user.device.set",
                "device": device.id,
                "expected_templates": False,
                "expected_slot": False,
                "expected_tech": False,
                "expected_medical": False,
                "expected_training": False,
            },
            "fields": [
                {
                    "name": "user",
                    "label": "DEV user",
                    "type": "select",
                    "required": True,
                    "options": quick_add_user_options,
                },
                {
                    "name": "templates",
                    "label": "templates",
                    "type": "checkbox",
                },
                {"name": "slot", "label": "edit any", "type": "checkbox"},
                {"name": "tech", "label": "tech", "type": "checkbox"},
                {"name": "medical", "label": "medical", "type": "checkbox"},
                {
                    "name": "training",
                    "label": "training",
                    "type": "checkbox",
                },
            ],
        }

    left_nodes, left_more = _rbac_slice_graph_nodes(source_nodes)
    right_nodes, right_more = _rbac_slice_graph_nodes(target_nodes)
    group_rows, group_more = _rbac_limit_rows(group_rows)
    special_rows, special_more = _rbac_limit_rows(special_rows)

    return {
        "summary": {
            "title": _rbac_device_label(device),
            "subtitle": "device",
            "badges": [_rbac_state(bool(device.active))],
        },
        "links": [],
        "graph": {
            "source_title": "linked groups",
            "target_title": "user-specific device permissions",
            "focus": {
                "label": _rbac_device_label(device),
                "href": "",
            },
            "sources": left_nodes,
            "targets": right_nodes,
            "source_more": left_more,
            "target_more": right_more,
        },
        "tables": [
            {
                "title": "group links",
                "empty": "No groups linked to this device.",
                "more": group_more,
                "columns": [
                    {"key": "group", "label": "group"},
                    {"key": "status", "label": "group status"},
                ],
                "rows": group_rows,
            },
            {
                "title": "device-specific user permissions",
                "empty": "No device-specific user permissions found.",
                "more": special_more,
                "columns": [
                    {"key": "user", "label": "user"},
                    {"key": "user_state", "label": "user state"},
                    {"key": "permissions", "label": "permissions"},
                ],
                "rows": special_rows,
            },
        ],
        "matrices": [
            {
                "id": "device-metadata-matrix",
                "title": "device settings",
                "description": "Edit device metadata and active state inline.",
                "empty": "Device metadata unavailable.",
                "apply_label": "apply device settings",
                "confirm": f"Apply metadata updates for {device.id}?",
                "more": 0,
                "filter": False,
                "layout": "keyvalue",
                "rows": [
                    {
                        "id": f"{device.id}-label",
                        "search": f"{device.id} label {_rbac_device_label(device)}",
                        "label": "label",
                        "kind": "input",
                        "input_type": "text",
                        "max_length": 25,
                        "field": "label",
                        "value": device.label or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-description",
                        "search": f"{device.id} description {_rbac_device_label(device)}",
                        "label": "description",
                        "kind": "input",
                        "input_type": "text",
                        "field": "description",
                        "value": device.description or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-addr",
                        "search": f"{device.id} email {_rbac_device_label(device)}",
                        "label": "email",
                        "kind": "input",
                        "input_type": "text",
                        "field": "addr",
                        "value": device.addr or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-tech-addr",
                        "search": f"{device.id} tech email {_rbac_device_label(device)}",
                        "label": "tech email",
                        "kind": "input",
                        "input_type": "text",
                        "field": "tech_addr",
                        "value": device.tech_addr or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-medical-addr",
                        "search": f"{device.id} medical email {_rbac_device_label(device)}",
                        "label": "medical email",
                        "kind": "input",
                        "input_type": "text",
                        "field": "med_addr",
                        "value": device.med_addr or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-training-addr",
                        "search": f"{device.id} training email {_rbac_device_label(device)}",
                        "label": "training email",
                        "kind": "input",
                        "input_type": "text",
                        "field": "train_addr",
                        "value": device.train_addr or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-active",
                        "search": f"{device.id} active {_rbac_device_label(device)}",
                        "label": "active",
                        "kind": "checkbox",
                        "field": "active",
                        "value": bool(device.active),
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                ],
            },
            {
                "id": "device-group-links-matrix",
                "title": "group links",
                "description": (
                    "Tick groups that should remain linked to this device."
                ),
                "empty": "No groups found.",
                "apply_label": "apply group links",
                "confirm": f"Apply group link updates for {device.id}?",
                "more": group_matrix_more,
                "columns": [
                    {"key": "group", "label": "group", "kind": "text"},
                    {"key": "group_state", "label": "group state", "kind": "text"},
                    {"key": "linked", "label": "linked", "kind": "checkbox"},
                ],
                "rows": group_matrix_rows,
            },
            {
                "id": "device-user-permissions-matrix",
                "title": "DEV user permissions",
                "description": (
                    "Edit per-user device flags directly. "
                    "Stale overrides can be cleared here."
                ),
                "empty": "No DEV users or overrides found.",
                "apply_label": "apply permission updates",
                "confirm": f"Apply user permission updates for {device.id}?",
                "more": user_matrix_more,
                "quick_add": quick_add_config,
                "columns": [
                    {"key": "user", "label": "user", "kind": "text"},
                    {"key": "user_state", "label": "user state", "kind": "text"},
                    {"key": "dev_member", "label": "DEV member", "kind": "text"},
                    {
                        "key": "technologist",
                        "label": "technologist",
                        "kind": "text",
                    },
                    {"key": "templates", "label": "templates", "kind": "checkbox"},
                    {"key": "slot", "label": "edit any", "kind": "checkbox"},
                    {"key": "tech", "label": "tech", "kind": "checkbox"},
                    {"key": "medical", "label": "medical", "kind": "checkbox"},
                    {"key": "training", "label": "training", "kind": "checkbox"},
                ],
                "rows": user_matrix_rows,
            },
        ],
        "mutations": [],
    }


def _rbac_user_detail(
    user: model.User,
    *,
    include_inactive: bool = False,
) -> Dict[str, Any]:
    memberships_query = (
        model.Membership.query.options(
            load_only(
                model.Membership.group,
                model.Membership.user,
                model.Membership.pi,
                model.Membership.approved,
                model.Membership.email_status,
                model.Membership.group_active,
                model.Membership.user_active,
            )
        )
        .filter(model.Membership.user == user.id)
        .order_by(model.Membership.group)
    )
    if not include_inactive:
        memberships_query = memberships_query.filter(model.Membership.group_active)
    memberships = memberships_query.all()
    user_perms_query = (
        model.db.session.query(model.UserDevice, model.Device)
        .join(model.Device, model.Device.id == model.UserDevice.device)
        .options(
            Load(model.UserDevice).load_only(
                model.UserDevice.user,
                model.UserDevice.device,
                model.UserDevice.templates,
                model.UserDevice.slot,
                model.UserDevice.tech,
                model.UserDevice.medical,
                model.UserDevice.training,
            ),
            Load(model.Device).load_only(
                model.Device.id, model.Device.label, model.Device.active
            ),
        )
        .filter(model.UserDevice.user == user.id)
        .order_by(model.Device.label, model.Device.id)
    )
    if not include_inactive:
        user_perms_query = user_perms_query.filter(model.Device.active)
    user_perms = user_perms_query.all()
    device_groups: Dict[str, set[str]] = {}
    for device_id, group_id in model.DeviceGroup.query.with_entities(
        model.DeviceGroup.device, model.DeviceGroup.group
    ).all():
        device_groups.setdefault(device_id, set()).add(group_id)
    user_perms_by_device = {ud.device: ud for ud, _ in user_perms}
    memberships_by_group = {row.group: row for row in memberships}

    is_admin = logic.is_admin(user)
    is_dev_pi = (
        model.Membership.query.filter(model.Membership.user == user.id)
        .filter(model.Membership.group == "DEV")
        .filter(model.Membership.pi)
        .filter(model.Membership.user_active)
        .filter(model.Membership.approved)
        .first()
        is not None
    )
    tech_request = model.Technologist.query.get(user.id)
    is_technologist = logic.is_technologist(user.id)
    tech_applied = tech_request is not None
    tech_email_status = _rbac_email_status(
        tech_request.email_status
        if tech_request is not None
        else logic.EMAIL_STATUS_NONE
    )
    is_dev_member, _ = logic.get_dev_tech_status(user)
    show_device_permissions = bool(is_dev_member)
    approved_groups = {
        row.group
        for row in memberships
        if row.user_active and row.group_active and row.approved
    }

    source_nodes: List[Dict[str, str]] = []
    membership_rows: List[Dict[str, Any]] = []
    for row in memberships:
        status = "approved" if row.approved else "pending"
        group_state = _rbac_state(bool(row.group_active))
        tags = [status, group_state]
        if row.pi:
            tags.append("PI")
        source_nodes.append(
            {
                "label": row.group,
                "meta": ", ".join(tags),
                "href": url_for("rbac", scope="group", entity=row.group),
            }
        )
        actions = [
            {
                "label": "inspect group",
                "href": url_for("rbac", scope="group", entity=row.group),
            }
        ]
        membership_rows.append(
            {
                "cells": {
                    "group": row.group,
                    "status": status,
                    "pi": _rbac_badge(bool(row.pi)),
                    "group_state": group_state,
                },
                "actions": actions,
            }
        )

    target_nodes: List[Dict[str, str]] = []
    special_rows: List[Dict[str, Any]] = []
    for ud, device in user_perms:
        if not show_device_permissions:
            continue
        flags = _rbac_permission_flags(ud)
        target_nodes.append(
            {
                "label": _rbac_device_label(device),
                "meta": flags,
                "href": url_for("rbac", scope="device", entity=device.id),
            }
        )
        actions = [
            {
                "label": "inspect device",
                "href": url_for("rbac", scope="device", entity=device.id),
            }
        ]
        special_rows.append(
            {
                "cells": {
                    "device": _rbac_device_label(device),
                    "status": _rbac_state(bool(device.active)),
                    "permissions": flags,
                },
                "actions": actions,
            }
        )

    all_groups_query = model.Group.query.options(
        load_only(
            model.Group.id,
            model.Group.label,
            model.Group.active,
            model.Group.has_membership,
        )
    ).order_by(model.Group.label, model.Group.id)
    if not include_inactive:
        all_groups_query = all_groups_query.filter(model.Group.active)
    all_groups = all_groups_query.all()
    membership_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for group in all_groups:
        membership = memberships_by_group.get(group.id)
        is_member = membership is not None
        approved = bool(membership.approved) if membership is not None else False
        pi = bool(membership.pi) if membership is not None else False
        email_status = (
            _rbac_email_status(membership.email_status)
            if membership is not None
            else logic.EMAIL_STATUS_NONE
        )
        membership_enabled = bool(group.has_membership)
        can_edit_membership = bool(group.active and (membership_enabled or is_member))
        row = {
            "id": group.id,
            "search": (
                f"{group.id} {_rbac_group_label(group)} "
                f"{_rbac_state(bool(group.active))} {email_status}"
            ),
            "cells": {
                "group": _rbac_group_label(group),
                "group_state": _rbac_state(bool(group.active)),
                "membership_enabled": _rbac_badge(membership_enabled),
                "pi": _rbac_badge(pi),
            },
            "values": {
                "member": is_member,
                "approved": approved,
                "email_status": email_status,
            },
            "editable": {
                "member": can_edit_membership,
                "approved": bool(can_edit_membership and is_member and user.active),
                "email_status": bool(
                    can_edit_membership and is_member and not approved
                ),
            },
            "operation": {
                "kind": "group.membership.set",
                "group": group.id,
                "user": user.id,
            },
        }
        rank = (
            0 if is_member else 1,
            0 if group.active else 1,
            (group.label or "").lower(),
            group.id.lower(),
        )
        membership_matrix_rows_ranked.append((rank, row))
    membership_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    membership_matrix_rows = [row for _, row in membership_matrix_rows_ranked]
    membership_matrix_rows, membership_matrix_more = _rbac_limit_rows(
        membership_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )

    all_devices_query = model.Device.query.options(
        load_only(model.Device.id, model.Device.label, model.Device.active)
    ).order_by(model.Device.label, model.Device.id)
    if not include_inactive:
        all_devices_query = all_devices_query.filter(model.Device.active)
    all_devices = all_devices_query.all()
    permission_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for device in all_devices:
        if not show_device_permissions:
            continue
        override = user_perms_by_device.get(device.id)
        templates = bool(override.templates) if override is not None else False
        slot = bool(override.slot) if override is not None else False
        tech = bool(override.tech) if override is not None else False
        medical = bool(override.medical) if override is not None else False
        training = bool(override.training) if override is not None else False
        has_override = any((templates, slot, tech, medical, training))
        inherited_edit = bool(
            approved_groups.intersection(device_groups.get(device.id, set()))
        )
        can_assign = bool(user.active and is_dev_member)
        row = {
            "id": device.id,
            "search": (
                f"{device.id} {_rbac_device_label(device)} "
                f"{_rbac_state(bool(device.active))}"
            ),
            "cells": {
                "device": _rbac_device_label(device),
                "device_state": _rbac_state(bool(device.active)),
                "group_edit": _rbac_badge(inherited_edit),
            },
            "values": {
                "templates": templates,
                "slot": slot,
                "tech": tech,
                "medical": medical,
                "training": training,
            },
            "editable": {
                "templates": bool(can_assign or templates),
                "slot": bool(can_assign or slot),
                "tech": bool((can_assign and is_technologist) or tech),
                "medical": bool(can_assign or medical),
                "training": bool(can_assign or training),
            },
            "operation": {
                "kind": "user.device.set",
                "user": user.id,
                "device": device.id,
            },
        }
        rank = (
            0 if has_override else 1,
            0 if inherited_edit else 1,
            0 if device.active else 1,
            (device.label or "").lower(),
            device.id.lower(),
        )
        permission_matrix_rows_ranked.append((rank, row))
    permission_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    permission_matrix_rows = [row for _, row in permission_matrix_rows_ranked]
    permission_matrix_rows, permission_matrix_more = _rbac_limit_rows(
        permission_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )

    left_nodes, left_more = _rbac_slice_graph_nodes(source_nodes)
    right_nodes, right_more = _rbac_slice_graph_nodes(target_nodes)
    membership_rows, membership_more = _rbac_limit_rows(membership_rows)
    special_rows, special_more = _rbac_limit_rows(special_rows)

    badges = [_rbac_state(bool(user.active))]
    if is_admin:
        badges.append("admin")
    if is_dev_pi:
        badges.append("DEV PI")
    if is_technologist:
        badges.append("technologist")

    tables: List[Dict[str, Any]] = [
        {
            "title": "group memberships",
            "empty": "No group memberships found for this user.",
            "more": membership_more,
            "columns": [
                {"key": "group", "label": "group"},
                {"key": "status", "label": "status"},
                {"key": "pi", "label": "pi"},
                {"key": "group_state", "label": "group state"},
            ],
            "rows": membership_rows,
        },
        {
            "title": "effective access guidance",
            "empty": "No additional guidance available.",
            "more": 0,
            "columns": [
                {"key": "note", "label": "note"},
            ],
            "rows": [
                {
                    "cells": {
                        "note": (
                            "Use the checkboxes below to edit explicit permissions. "
                            "Group-linked access remains implicit."
                        )
                    },
                    "actions": [],
                }
            ],
        },
    ]
    if show_device_permissions:
        tables.insert(
            1,
            {
                "title": "device-specific permissions",
                "empty": "No userdevice permissions found for this user.",
                "more": special_more,
                "columns": [
                    {"key": "device", "label": "device"},
                    {"key": "status", "label": "device state"},
                    {"key": "permissions", "label": "permissions"},
                ],
                "rows": special_rows,
            },
        )

    matrices: List[Dict[str, Any]] = [
        {
            "id": "user-settings-matrix",
            "title": "user settings",
            "description": (
                "Edit user profile state, including technologist request workflow."
            ),
            "empty": "User settings unavailable.",
            "apply_label": "apply user settings",
            "confirm": f"Apply user settings updates for {user.id}?",
            "more": 0,
            "filter": False,
            "layout": "keyvalue",
            "rows": [
                {
                    "id": f"{user.id}-active",
                    "search": f"{user.id} active {_rbac_user_label(user)}",
                    "label": "active",
                    "kind": "checkbox",
                    "field": "active",
                    "value": bool(user.active),
                    "editable": True,
                    "operation": {"kind": "user.active.set", "user": user.id},
                },
                {
                    "id": f"{user.id}-email",
                    "search": f"{user.id} email {_rbac_user_label(user)} {user.addr or ''}",
                    "label": "email",
                    "kind": "input",
                    "input_type": "text",
                    "field": "addr",
                    "value": user.addr or "",
                    "editable": True,
                    "operation": {
                        "kind": "user.profile.set",
                        "user": user.id,
                        "expected_addr": user.addr or "",
                    },
                },
                {
                    "id": f"{user.id}-admin",
                    "search": f"{user.id} admin {_rbac_user_label(user)}",
                    "label": "admin",
                    "kind": "checkbox",
                    "value": bool(is_admin),
                    "editable": False,
                },
                {
                    "id": f"{user.id}-dev-pi",
                    "search": f"{user.id} dev pi {_rbac_user_label(user)}",
                    "label": "DEV PI",
                    "kind": "checkbox",
                    "value": bool(is_dev_pi),
                    "editable": False,
                },
                {
                    "id": f"{user.id}-technologist-applied",
                    "search": (
                        f"{user.id} technologist applied {_rbac_user_label(user)} "
                        f"{_rbac_badge(bool(tech_applied))}"
                    ),
                    "label": "technologist applied",
                    "kind": "checkbox",
                    "field": "applied",
                    "value": bool(tech_applied),
                    "editable": True,
                    "operation": {
                        "kind": "user.technologist.set",
                        "user": user.id,
                        "applied": bool(tech_applied),
                        "approved": bool(is_technologist),
                        "email_status": tech_email_status,
                        "expected_applied": bool(tech_applied),
                        "expected_approved": bool(is_technologist),
                        "expected_email_status": tech_email_status,
                    },
                },
                {
                    "id": f"{user.id}-technologist-approved",
                    "search": (
                        f"{user.id} technologist approved {_rbac_user_label(user)} "
                        f"{_rbac_badge(bool(is_technologist))}"
                    ),
                    "label": "technologist approved",
                    "kind": "checkbox",
                    "field": "approved",
                    "value": bool(is_technologist),
                    "editable": True,
                    "operation": {
                        "kind": "user.technologist.set",
                        "user": user.id,
                        "applied": bool(tech_applied),
                        "approved": bool(is_technologist),
                        "email_status": tech_email_status,
                        "expected_applied": bool(tech_applied),
                        "expected_approved": bool(is_technologist),
                        "expected_email_status": tech_email_status,
                    },
                },
                {
                    "id": f"{user.id}-technologist-email",
                    "search": (
                        f"{user.id} technologist email {_rbac_user_label(user)} "
                        f"{tech_email_status}"
                    ),
                    "label": "technologist email",
                    "kind": "select",
                    "field": "email_status",
                    "value": tech_email_status,
                    "options": _RBAC_EMAIL_STATUS_OPTIONS,
                    "editable": bool(tech_applied and not is_technologist),
                    "operation": {
                        "kind": "user.technologist.set",
                        "user": user.id,
                        "applied": bool(tech_applied),
                        "approved": bool(is_technologist),
                        "email_status": tech_email_status,
                        "expected_applied": bool(tech_applied),
                        "expected_approved": bool(is_technologist),
                        "expected_email_status": tech_email_status,
                    },
                },
            ],
        },
        {
            "id": "user-group-memberships-matrix",
            "title": "group memberships",
            "description": "Review and update membership and approval state across groups.",
            "empty": "No groups found.",
            "apply_label": "apply membership updates",
            "confirm": f"Apply membership updates for {user.id}?",
            "more": membership_matrix_more,
            "columns": [
                {"key": "group", "label": "group", "kind": "text"},
                {"key": "group_state", "label": "group state", "kind": "text"},
                {
                    "key": "membership_enabled",
                    "label": "membership-enabled",
                    "kind": "text",
                },
                {"key": "member", "label": "member", "kind": "checkbox"},
                {"key": "approved", "label": "approved", "kind": "checkbox"},
                {
                    "key": "email_status",
                    "label": "email",
                    "kind": "select",
                    "options": _RBAC_EMAIL_STATUS_OPTIONS,
                },
                {"key": "pi", "label": "PI", "kind": "text"},
            ],
            "rows": membership_matrix_rows,
            "behavior": "group-membership",
        },
    ]
    if show_device_permissions:
        matrices.append(
            {
                "id": "user-device-permissions-matrix",
                "title": "device-specific permissions",
                "description": (
                    "Tick explicit device flags. Group-linked edit access is shown in "
                    '"group edit" for context.'
                ),
                "empty": "No devices found.",
                "apply_label": "apply permission updates",
                "confirm": f"Apply device permission updates for {user.id}?",
                "more": permission_matrix_more,
                "columns": [
                    {"key": "device", "label": "device", "kind": "text"},
                    {"key": "device_state", "label": "device state", "kind": "text"},
                    {"key": "group_edit", "label": "group edit", "kind": "text"},
                    {"key": "templates", "label": "templates", "kind": "checkbox"},
                    {"key": "slot", "label": "edit any", "kind": "checkbox"},
                    {"key": "tech", "label": "tech", "kind": "checkbox"},
                    {"key": "medical", "label": "medical", "kind": "checkbox"},
                    {"key": "training", "label": "training", "kind": "checkbox"},
                ],
                "rows": permission_matrix_rows,
            }
        )

    return {
        "summary": {
            "title": _rbac_user_label(user),
            "subtitle": "user",
            "badges": badges,
        },
        "links": [],
        "graph": {
            "source_title": "group memberships",
            "target_title": "device-specific permissions",
            "focus": {"label": _rbac_user_label(user), "href": ""},
            "sources": left_nodes,
            "targets": right_nodes,
            "source_more": left_more,
            "target_more": right_more,
        },
        "tables": tables,
        "matrices": matrices,
        "mutations": [],
    }


def _rbac_empty_detail(scope: str) -> Dict[str, Any]:
    label = _RBAC_SCOPE_LABELS.get(scope, "items")
    return {
        "summary": {
            "title": f"No {label} found",
            "subtitle": "RBAC explorer",
            "badges": [],
        },
        "links": [],
        "graph": {
            "source_title": "source",
            "target_title": "target",
            "focus": {"label": "Nothing selected", "href": ""},
            "sources": [],
            "targets": [],
            "source_more": 0,
            "target_more": 0,
        },
        "tables": [],
        "matrices": [],
        "mutations": [],
    }


def _rbac_detail(
    scope: str,
    entity: str,
    *,
    include_inactive: bool = False,
) -> Dict[str, Any]:
    if scope == "group":
        group = logic.get_group(entity)
        if group is None:
            abort(404, f"group not found: {entity}")
        if not include_inactive and not group.active:
            abort(404, f"group not found: {entity}")
        return _rbac_group_detail(group, include_inactive=include_inactive)

    if scope == "device":
        device = logic.get_device(entity)
        if device is None:
            abort(404, f"device not found: {entity}")
        if not include_inactive and not device.active:
            abort(404, f"device not found: {entity}")
        return _rbac_device_detail(device, include_inactive=include_inactive)

    if scope == "user":
        user = logic.get_user(entity)
        if user is None:
            abort(404, f"user not found: {entity}")
        if not include_inactive and not user.active:
            abort(404, f"user not found: {entity}")
        return _rbac_user_detail(user, include_inactive=include_inactive)

    abort(400, f"invalid scope: {scope}")


def _rbac_restrict_detail_for_actor(
    scope: str,
    detail: Dict[str, Any],
    actor: Dict[str, Any],
) -> Dict[str, Any]:
    from .rbac_explorer_serialization import (
        _rbac_restrict_detail_for_actor as _rbac_restrict_detail_for_actor_impl,
    )

    return _rbac_restrict_detail_for_actor_impl(scope, detail, actor)
