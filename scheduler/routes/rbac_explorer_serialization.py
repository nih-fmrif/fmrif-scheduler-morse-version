"""RBAC explorer payload serialization and response shaping helpers."""

from ._rbac_explorer_core import _rbac_href_allowed_for_actor
from ._rbac_explorer_payloads import RbacActor, RbacDetail, RbacMatrix


def _rbac_restrict_detail_for_actor(
    scope: str,
    detail: RbacDetail,
    actor: RbacActor,
) -> RbacDetail:
    if bool(actor.get("is_admin")):
        return detail

    matrices = detail.get("matrices", [])
    if not isinstance(matrices, list):
        return detail

    restricted: list[RbacMatrix] = []
    for matrix in matrices:
        if not isinstance(matrix, dict):
            continue
        matrix_id = str(matrix.get("id", ""))

        if scope == "group":
            if matrix_id == "group-device-links-matrix":
                # Device linkage remains a DEV PI/admin capability.
                continue
            if matrix_id == "group-metadata-matrix":
                rows = matrix.get("rows", [])
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        field = str(row.get("field", ""))
                        if field in {"inst", "active"}:
                            row["editable"] = False
            restricted.append(matrix)
            continue

        if scope == "device":
            if matrix_id == "device-metadata-matrix":
                rows = matrix.get("rows", [])
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        if str(row.get("field", "")) == "active":
                            row["editable"] = False
            restricted.append(matrix)
            continue

        restricted.append(matrix)

    detail["matrices"] = restricted

    graph = detail.get("graph", {})
    if isinstance(graph, dict):
        focus = graph.get("focus", {})
        if isinstance(focus, dict):
            href = str(focus.get("href", ""))
            if not _rbac_href_allowed_for_actor(href, actor):
                focus["href"] = ""
        for side in ("sources", "targets"):
            nodes = graph.get(side, [])
            if not isinstance(nodes, list):
                continue
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                href = str(node.get("href", ""))
                if not _rbac_href_allowed_for_actor(href, actor):
                    node["href"] = ""

    tables = detail.get("tables", [])
    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue
            rows = table.get("rows", [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                actions = row.get("actions", [])
                if not isinstance(actions, list):
                    continue
                filtered_actions = []
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    href = str(action.get("href", ""))
                    if _rbac_href_allowed_for_actor(href, actor):
                        filtered_actions.append(action)
                row["actions"] = filtered_actions

    return detail


__all__ = ["_rbac_restrict_detail_for_actor"]
