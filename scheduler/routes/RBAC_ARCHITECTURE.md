# RBAC Route Architecture

This directory uses a small set of focused modules for RBAC behavior.

## Module map

- `rbac_routes.py`
  - Flask route handlers and blueprint registration.
  - Thin HTTP orchestration only.
- `rbac_explorer.py`
  - RBAC explorer actor/scope/entity/detail payload shaping.
- `rbac_audit.py`
  - Audit feed query + payload normalization helpers.
- `rbac_issues.py`
  - Admin "potential issues" detection and section grouping.
- `rbac_mutations.py`
  - Mutation orchestration (request parsing entrypoint, validation/apply loop, commit/rollback semantics).
- `rbac_mutation_validation.py`
  - Mutation payload parsing and normalization for each operation kind.
- `rbac_mutation_apply.py`
  - Mutation authorization and side-effect execution for each operation kind.

## Mutation flow

`POST /json/v1/rbac/mutate` executes in this order:

1. `rbac_routes.rbac_explorer_mutate()` validates scope + CSRF.
2. `rbac_mutations._rbac_mutate_batch()` orchestrates.
3. `rbac_mutation_validation._rbac_parse_batch_operations()` parses `operations` JSON.
4. `rbac_mutation_validation._rbac_validate_batch_operation()` normalizes each item.
5. `rbac_mutation_apply._rbac_authorize_batch_operation()` enforces actor constraints.
6. `rbac_mutation_apply._rbac_apply_batch_operation()` applies state changes + audit events.
7. `rbac_mutations._rbac_mutate_batch()` commits or rolls back atomically.

## Where to edit

- Add or change operation payload fields:
  - `rbac_mutation_validation.py`
- Change mutation DB side effects or audit text:
  - `rbac_mutation_apply.py`
- Change status codes / response envelope / atomic behavior:
  - `rbac_mutations.py`
- Change explorer UI data shape:
  - `rbac_explorer.py`
- Change audit page/feed behavior:
  - `rbac_audit.py`, `rbac_routes.py`
- Change admin panel issue rules:
  - `rbac_issues.py`

## Guardrails

- Keep endpoint names and URL rules stable unless route contracts are updated.
- Keep RBAC mutations atomic per request (all-or-nothing).
- Update route contract tests for route changes (`tests/unit/route_contract.py`).
