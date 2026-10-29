from __future__ import annotations

from typing import Any, Dict, List, Tuple

from flask import abort, current_app, request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from scheduler import model

from .rbac_mutation_apply import (
    _rbac_apply_batch_operation,
    _rbac_authorize_batch_operation,
    _RBACConflictError,
    _request_client_ip,
)
from .rbac_mutation_validation import (
    _rbac_parse_batch_operations,
    _rbac_validate_batch_operation,
)


def _rbac_required_form_value(name: str) -> str:
    value = request.form.get(name, "").strip()
    if value == "":
        abort(400, f"missing field: {name}")
    return value


def _rbac_mutate_batch(
    scope: str, entity: str, *, actor: Dict[str, Any]
) -> Tuple[Dict[str, Any], int]:
    operations = _rbac_parse_batch_operations(_rbac_required_form_value("operations"))
    if len(operations) == 0:
        return (
            {
                "ok": True,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": 0,
                "results": [],
                "message": "No changes submitted.",
            },
            200,
        )

    validated: List[Dict[str, Any]] = []
    validation_results: List[Dict[str, Any]] = []
    has_validation_error = False
    for index, operation in enumerate(operations):
        kind = str(operation.get("kind", "")).strip() or "unknown"
        try:
            normalized = _rbac_validate_batch_operation(
                operation, scope=scope, entity=entity
            )
            validated.append(normalized)
            validation_results.append(
                {"index": index, "kind": kind, "status": "pending", "message": ""}
            )
        except ValueError as ex:
            has_validation_error = True
            validation_results.append(
                {
                    "index": index,
                    "kind": kind,
                    "status": "invalid",
                    "message": str(ex),
                }
            )

    if has_validation_error:
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": validation_results,
                "message": "Validation failed. No RBAC changes were applied.",
            },
            400,
        )

    has_authz_error = False
    for index, validated_operation in enumerate(validated):
        try:
            _rbac_authorize_batch_operation(validated_operation, actor)
        except PermissionError as ex:
            has_authz_error = True
            validation_results[index]["status"] = "forbidden"
            validation_results[index]["message"] = str(ex)

    if has_authz_error:
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": validation_results,
                "message": "Permission denied. No RBAC changes were applied.",
            },
            403,
        )

    source_ip = _request_client_ip()
    results: List[Dict[str, Any]] = []
    try:
        for index, validated_operation in enumerate(validated):
            try:
                message, changed = _rbac_apply_batch_operation(
                    validated_operation, source_ip=source_ip
                )
            except _RBACConflictError as ex:
                results.append(
                    {
                        "index": index,
                        "kind": validated_operation["kind"],
                        "status": "conflict",
                        "message": str(ex),
                    }
                )
                raise
            results.append(
                {
                    "index": index,
                    "kind": validated_operation["kind"],
                    "status": "applied" if changed else "unchanged",
                    "message": message,
                }
            )

        model.db.session.commit()
    except _RBACConflictError as ex:
        model.db.session.rollback()
        for row in results:
            if row["status"] == "applied":
                row["status"] = "rolled_back"
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": results,
                "message": str(ex),
            },
            409,
        )
    except ValueError as ex:
        model.db.session.rollback()
        for row in results:
            if row["status"] == "applied":
                row["status"] = "rolled_back"
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": results,
                "message": str(ex),
            },
            400,
        )
    except IntegrityError:
        model.db.session.rollback()
        for row in results:
            if row["status"] == "applied":
                row["status"] = "rolled_back"
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": results,
                "message": "RBAC data changed concurrently. No RBAC changes were applied.",
            },
            409,
        )
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("RBAC batch mutation failed")
        for row in results:
            if row["status"] == "applied":
                row["status"] = "rolled_back"
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": results,
                "message": "Failed to apply RBAC batch updates.",
            },
            500,
        )

    applied_count = sum(1 for row in results if row["status"] == "applied")
    return (
        {
            "ok": True,
            "atomic": True,
            "scope": scope,
            "entity": entity,
            "applied": applied_count,
            "total": len(operations),
            "results": results,
            "message": (
                f"Applied {applied_count} of {len(operations)} requested RBAC changes."
            ),
        },
        200,
    )
