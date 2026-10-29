from __future__ import annotations

from typing import Any, Dict

from ._rbac_mutation_shared import _rbac_parse_batch_operations  # noqa: F401
from ._rbac_mutation_validation_entities import ENTITY_VALIDATORS
from ._rbac_mutation_validation_relationships import RELATIONSHIP_VALIDATORS

_RBAC_BATCH_VALIDATORS = {
    **ENTITY_VALIDATORS,
    **RELATIONSHIP_VALIDATORS,
}


def _rbac_validate_batch_operation(
    operation: Dict[str, Any],
    *,
    scope: str,
    entity: str,
) -> Dict[str, Any]:
    kind = str(operation.get("kind", "")).strip()
    if kind == "":
        raise ValueError("operation kind is required")

    validator = _RBAC_BATCH_VALIDATORS.get(kind)
    if validator is None:
        raise ValueError(f"unsupported operation kind: {kind}")
    return validator(operation, scope=scope, entity=entity)
