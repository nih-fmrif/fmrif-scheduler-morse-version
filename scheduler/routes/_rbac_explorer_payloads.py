"""Typed RBAC explorer payload helpers shared across route modules."""

from __future__ import annotations

from typing import Any, Mapping, TypedDict


class RbacActor(TypedDict):
    id: str
    is_admin: bool
    is_dev_pi: bool
    managed_groups: set[str]
    allowed_scopes: list[str]
    can_access: bool


class RbacEntityOption(TypedDict):
    id: str
    label: str
    active: bool


class RbacSelectOption(TypedDict, total=False):
    value: str
    label: str
    meta: str


class RbacGraphFocus(TypedDict):
    label: str
    href: str


class RbacGraphNode(TypedDict):
    label: str
    meta: str
    href: str


class RbacTableAction(TypedDict):
    label: str
    href: str


class RbacTableRow(TypedDict):
    cells: dict[str, Any]
    actions: list[RbacTableAction]


class RbacKeyValueRow(TypedDict, total=False):
    id: str
    search: str
    label: str
    kind: str
    input_type: str
    max_length: int
    field: str
    value: Any
    options: list[RbacSelectOption]
    editable: bool
    operation: dict[str, Any]


class RbacMatrixRow(TypedDict):
    id: str
    search: str
    cells: dict[str, Any]
    values: dict[str, Any]
    editable: dict[str, bool]
    operation: dict[str, Any]


class RbacColumn(TypedDict, total=False):
    key: str
    label: str
    kind: str
    options: list[RbacSelectOption]


class RbacQuickAddField(TypedDict, total=False):
    name: str
    label: str
    type: str
    required: bool
    options: list[RbacSelectOption]


class RbacQuickAddConfig(TypedDict):
    label: str
    title: str
    submit_label: str
    scope: str
    entity: str
    operation: dict[str, Any]
    fields: list[RbacQuickAddField]


class RbacTable(TypedDict):
    title: str
    empty: str
    more: int
    columns: list[RbacColumn]
    rows: list[RbacTableRow]


class RbacMatrix(TypedDict, total=False):
    id: str
    title: str
    description: str
    empty: str
    apply_label: str
    confirm: str
    more: int
    filter: bool
    layout: str
    quick_add: RbacQuickAddConfig | None
    columns: list[RbacColumn]
    rows: list[RbacMatrixRow | RbacKeyValueRow]
    behavior: str


class RbacSummary(TypedDict):
    title: str
    subtitle: str
    badges: list[str]


class RbacGraph(TypedDict):
    source_title: str
    target_title: str
    focus: RbacGraphFocus
    sources: list[RbacGraphNode]
    targets: list[RbacGraphNode]
    source_more: int
    target_more: int


class RbacDetail(TypedDict):
    summary: RbacSummary
    links: list[dict[str, Any]]
    graph: RbacGraph
    tables: list[RbacTable]
    matrices: list[RbacMatrix]
    mutations: list[dict[str, Any]]


def build_rbac_actor(
    *,
    actor_id: str,
    is_admin: bool = False,
    is_dev_pi: bool = False,
    managed_groups: set[str] | None = None,
    allowed_scopes: list[str] | None = None,
    can_access: bool = False,
) -> RbacActor:
    return {
        "id": actor_id,
        "is_admin": is_admin,
        "is_dev_pi": is_dev_pi,
        "managed_groups": managed_groups or set(),
        "allowed_scopes": allowed_scopes or [],
        "can_access": can_access,
    }


def build_entity_option(
    *, entity_id: str, label: str, active: bool
) -> RbacEntityOption:
    return {"id": entity_id, "label": label, "active": active}


def build_select_option(*, value: str, label: str, meta: str = "") -> RbacSelectOption:
    option: RbacSelectOption = {"value": value, "label": label}
    if meta:
        option["meta"] = meta
    return option


def build_graph_focus(*, label: str, href: str = "") -> RbacGraphFocus:
    return {"label": label, "href": href}


def build_graph_node(*, label: str, meta: str = "", href: str = "") -> RbacGraphNode:
    return {"label": label, "meta": meta, "href": href}


def build_table_action(*, label: str, href: str) -> RbacTableAction:
    return {"label": label, "href": href}


def build_table_row(
    *,
    cells: Mapping[str, Any],
    actions: list[RbacTableAction] | None = None,
) -> RbacTableRow:
    return {"cells": dict(cells), "actions": list(actions or [])}


def build_matrix_row(
    *,
    row_id: str,
    search: str,
    cells: Mapping[str, Any],
    values: Mapping[str, Any],
    editable: Mapping[str, bool],
    operation: Mapping[str, Any],
) -> RbacMatrixRow:
    return {
        "id": row_id,
        "search": search,
        "cells": dict(cells),
        "values": dict(values),
        "editable": dict(editable),
        "operation": dict(operation),
    }


def build_keyvalue_row(
    *,
    row_id: str,
    search: str,
    label: str,
    kind: str,
    value: Any,
    editable: bool,
    field: str = "",
    input_type: str = "",
    max_length: int | None = None,
    options: list[RbacSelectOption] | None = None,
    operation: Mapping[str, Any] | None = None,
) -> RbacKeyValueRow:
    row: RbacKeyValueRow = {
        "id": row_id,
        "search": search,
        "label": label,
        "kind": kind,
        "value": value,
        "editable": editable,
    }
    if field:
        row["field"] = field
    if input_type:
        row["input_type"] = input_type
    if max_length is not None:
        row["max_length"] = max_length
    if options is not None:
        row["options"] = list(options)
    if operation is not None:
        row["operation"] = dict(operation)
    return row


def build_column(
    *,
    key: str,
    label: str,
    kind: str = "text",
    options: list[RbacSelectOption] | None = None,
) -> RbacColumn:
    column: RbacColumn = {"key": key, "label": label}
    if kind:
        column["kind"] = kind
    if options is not None:
        column["options"] = list(options)
    return column


__all__ = [
    "RbacActor",
    "RbacColumn",
    "RbacDetail",
    "RbacEntityOption",
    "RbacGraphNode",
    "RbacKeyValueRow",
    "RbacMatrix",
    "RbacMatrixRow",
    "RbacQuickAddConfig",
    "RbacQuickAddField",
    "RbacSelectOption",
    "RbacTable",
    "RbacTableAction",
    "RbacTableRow",
    "build_column",
    "build_entity_option",
    "build_graph_focus",
    "build_graph_node",
    "build_keyvalue_row",
    "build_matrix_row",
    "build_rbac_actor",
    "build_select_option",
    "build_table_action",
    "build_table_row",
]
