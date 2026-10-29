from __future__ import annotations

from typing import Any, Dict

from ._rbac_mutation_apply_support import _rbac_actor_managed_groups


def _rbac_authorize_batch_operation(
    validated: Dict[str, Any], actor: Dict[str, Any]
) -> None:
    if bool(actor.get("is_admin")):
        return

    kind = str(validated.get("kind", ""))
    managed_groups = _rbac_actor_managed_groups(actor)
    is_dev_pi = bool(actor.get("is_dev_pi"))

    if kind in {"group.meta.set", "group.membership.set", "group.pi.set"}:
        group = validated["group"]
        if group.id not in managed_groups:
            raise PermissionError(f"group not managed by current user: {group.id}")
        if not bool(group.active):
            raise PermissionError(f"inactive group requires admin access: {group.id}")
        if kind == "group.meta.set":
            if (validated.get("inst") or "") != (group.inst or ""):
                raise PermissionError("group institute edits require admin access")
            if bool(validated.get("active")) != bool(group.active):
                raise PermissionError("group active-state edits require admin access")
        return

    if kind in {"device.meta.set", "device.group.set", "user.device.set"}:
        if not is_dev_pi:
            raise PermissionError("device RBAC updates require DEV PI or admin access")
        device = validated["device"]
        if not bool(device.active):
            raise PermissionError(f"inactive device requires admin access: {device.id}")
        if kind == "device.meta.set" and bool(validated.get("active")) != bool(
            device.active
        ):
            raise PermissionError("device active-state edits require admin access")
        return

    raise PermissionError(f"operation requires admin access: {kind}")
