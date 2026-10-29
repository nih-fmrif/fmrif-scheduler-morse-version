"""RBAC explorer read-model and query shaping helpers."""

from ._rbac_explorer_core import (
    _RBAC_AUDIT_SCOPE_LABELS,
    _RBAC_SCOPE_LABELS,
    _rbac_actor,
    _rbac_actor_allows_scope,
    _rbac_actor_scope_labels,
    _rbac_detail,
    _rbac_empty_detail,
    _rbac_entities_for_actor,
    _rbac_entity_visible_for_actor,
    _rbac_scopes,
)

__all__ = [
    "_RBAC_SCOPE_LABELS",
    "_RBAC_AUDIT_SCOPE_LABELS",
    "_rbac_actor",
    "_rbac_actor_allows_scope",
    "_rbac_actor_scope_labels",
    "_rbac_scopes",
    "_rbac_entities_for_actor",
    "_rbac_entity_visible_for_actor",
    "_rbac_empty_detail",
    "_rbac_detail",
]
