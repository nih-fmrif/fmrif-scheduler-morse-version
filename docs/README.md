# Scheduler Project Documentation

## Start Here
1. [Configuration Guide](configuration-guide.md)
2. [Testing Guide](testing-guide.md)
3. [Alembic Management Model](alembic-management-model.md)
4. [Deployment Boundary](deployment-considerations.md)

## Development Reference
1. [Testing Strategy](testing-strategy.md)
2. [Containerized PostgreSQL Guide](containerized-postgres.md)
3. [Security Guide](security.md)
4. [Scheduler Design](scheduler-design.md)
5. [RBAC Guide](RBAC.md)
6. [Scheduler Editability Policy](scheduler-editability-policy.md)
7. [Scheduler Editability Implementation Plan](scheduler-editability-implementation-plan.md)
8. [UX Guidelines](ux-guidelines.md)
9. [CSS Style Ownership](css-style-ownership.md)
10. [SQL Bootstrap Compatibility](sql-bootstrap-compatibility.md)
11. [Mapping Organizational Groups Resolution Path](mapping-organizational-groups-resolution-path.md)

## Agent guidance
1. [Agent Guidance: Quickstart](agent-guidance-quickstart.md)
2. [Agent Guidance: Isolation Validation](agent-guidance-isolation-validation.md)
3. [Agent Guidance: Playwright](agent-guidance-playwright.md)

## Operator Docs

Operator-facing deployment and maintenance material lives in the private
`fmrif-scheduler-docs` submodule:

1. [Submodule README](../fmrif-scheduler-docs/README.md)
2. [Operator deployment runbook](../fmrif-scheduler-docs/deployment.md)
3. [Host verification path](../fmrif-scheduler-docs/host-verification-path.md)
4. [DB operations](../fmrif-scheduler-docs/db-operations.md)

The main repository keeps the code-facing invariants needed to understand,
configure, and validate the app. Host-specific commands, service wiring,
maintenance procedures, and sensitive deployment detail belong in the submodule.

## Schema Management

The schema is managed by three layers with different responsibilities:

- `scheduler/model.py` reflects the parts of the schema the app uses, but it is
  not a 1:1 DDL definition of the whole database.
- Alembic migrations in `scheduler/alembic/` own live app-relevant schema
  changes after the initial deployment stamp point.
- SQL in `sql/` remains bootstrap and compatibility machinery for development,
  testing, and the supported initial-deployment workflow.

For the ownership model and the initial-deployment boundary, see
[`alembic-management-model.md`](alembic-management-model.md).
