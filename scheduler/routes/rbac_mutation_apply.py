from __future__ import annotations

from typing import Any, Dict, Tuple

from ._rbac_mutation_apply_entities import ENTITY_APPLIERS
from ._rbac_mutation_apply_relationships import RELATIONSHIP_APPLIERS
from ._rbac_mutation_apply_support import _request_client_ip  # noqa: F401
from ._rbac_mutation_authorization import _rbac_authorize_batch_operation  # noqa: F401
from ._rbac_mutation_shared import _RBACConflictError  # noqa: F401

_RBAC_APPLIERS = {
    **ENTITY_APPLIERS,
    **RELATIONSHIP_APPLIERS,
}


def _rbac_apply_batch_operation(
    validated: Dict[str, Any],
    *,
    source_ip: str,
) -> Tuple[str, bool]:
    kind = str(validated.get("kind", ""))
    applier = _RBAC_APPLIERS.get(kind)
    if applier is None:
        raise ValueError(f"unsupported operation kind: {kind}")
    return applier(validated, source_ip=source_ip)
