# Alembic Management Model

## Purpose

This document describes the database ownership model for this project under the
supported hybrid approach:

- raw SQL bootstrap is allowed for initial deployment and compatibility rebuilds
- Alembic owns live app-relevant schema evolution after the initial stamp point
- operational tooling may own operational workflows without becoming a second
  live schema-migration authority

This document complements:

- [Deployment Boundary](deployment-considerations.md)
- [SQL Bootstrap Compatibility](sql-bootstrap-compatibility.md)

The goal is to keep the hybrid model narrow enough that production changes do
not silently drift outside the application's reviewed upgrade path.

## Summary

The important distinctions are:

- `scheduler/model.py` is an application-facing reflection of the schema, not a
  full DDL specification
- Alembic can still own the live schema, but that ownership cannot rely on
  ORM/autogenerate alone
- any app-relevant table, view, trigger, function, constraint, or data repair
  that changes production behavior must be represented in Alembic, including
  handwritten migrations when necessary
- operational tooling may manage provisioning, credential rotation, backups,
  restore drills, and observability without weakening Alembic ownership of the
  live app schema
- bootstrap concerns such as database creation, legacy import, and initial
  reconciliation are allowed outside Alembic, but only before the database is
  stamped and treated as live

This model remains safe only when ownership is explicit.

## Deployment Lifecycle

### Initial Deployment

Initial deployment is the one-time creation of the production database from a
`003`-contract legacy dump plus any required reconciliation and relationship
hydration.

This establishes the first supported state for the new application.

### Live Deployment

After the database has been stamped to an Alembic revision, normal deployments
must treat Alembic as the only authority for live app-relevant schema changes.

That means a live deployment consists of:

- applying the relevant Alembic revisions
- verifying `alembic current` and `alembic_version`
- running application smoke checks

### Rollback Model

After initial deployment, rollback means:

1. restore a post-deployment backup
2. redeploy an application release that is compatible with the restored
   schema/data state

There is no supported rollback path to a pre-initial-deployment database state.

## Current Repo Shape

The current repository already shows why a pure "models are the whole database"
story is inaccurate:

- `scheduler/model.py` explicitly says the reflection is "not 1:1"
- deprecated tables and columns are intentionally left out
- some views are exposed to the application instead of the underlying tables
- `scheduler/alembic/env.py` still sets `target_metadata = None`, so the repo is
  not currently configured around metadata-driven autogenerate
- the Alembic history that is checked in covers only a subset of the total
  schema history represented in `sql/`

Examples of database objects the application depends on but which are not
simple ORM table declarations:

- `membership` view in `sql/190-add-views.sql`
- `app_log_json` view in `sql/190-add-views.sql`
- `soft_del_inst()` trigger function and `delete_inst` trigger in
  `sql/009-fix-up-institutes.sql`
- `log_sched_changes_impl()` trigger function in
  `sql/014-add-logging-back.sql`
- `log_support_impl()` trigger function in
  `sql/106-add-support-requests.sql`

Examples of one-time bootstrap/import behavior that do not belong in normal
post-deployment schema ownership:

- PostgreSQL readiness checks in `sql/000-init.sh`
- terminating sessions, dropping the database, and creating the database with
  explicit `ENCODING`, `LC_COLLATE`, `LC_CTYPE`, and `TEMPLATE=template0` in
  `sql/000-init.sh`
- legacy import and data repair steps in files such as
  `sql/003-import-data.sql`, `sql/002-loosen-schema.sql`,
  `sql/004-tighten-schema.sql`, and `sql/015-reseachers.sql`

## Ownership Model

### 1. Bootstrap-Owned Concerns

These concerns may remain outside Alembic:

- creating the database itself
- choosing database-level locale, encoding, and template
- one-time import of legacy or seed data needed to establish the initial live
  state
- one-time data reconciliation steps needed only to convert legacy data into the
  app's baseline shape
- documented installation and initial-deployment runbooks

These steps are allowed before the live database is stamped to an Alembic
revision. After that point they are no longer part of routine schema
management.

### 2. App-Owned Live Schema

Once deployment is complete and the database has been stamped, the application
must own all app-relevant schema changes through Alembic.

That includes:

- tables used directly by the application
- constraints and indexes that affect application correctness
- views queried by the application
- functions and triggers that affect application semantics
- app-owned data backfills and normalization steps needed during a deployment
- session or token storage tables used by the app
- admin/runtime configuration tables used by the app

This remains true even when the object is not represented cleanly in the ORM.
In those cases the migration must be handwritten.

### 3. Operator-Owned Non-App Objects

Operators may manage their own database objects outside Alembic, but only if
those objects are clearly outside the application's contract.

Reasonable examples:

- read-only reporting views or materialized views not queried by the app
- maintenance helpers used only by operators
- backup metadata tables if the app does not depend on them for business logic
- monitoring helpers that do not change application behavior

Unsafe examples:

- triggers on app-owned tables created outside Alembic
- constraints on app-owned tables added outside Alembic
- columns, defaults, or indexes added to app-owned tables outside Alembic
- operator-managed views that the app queries, if those views are not also
  tracked in Alembic

The rule is simple: if the app depends on it, Alembic must own it.

## Why The ORM Mismatch Is Not A Show-Stopper

The fact that `scheduler/model.py` is not 1:1 with the full database is a real
constraint, but not a blocker.

### What The Mismatch Actually Means

The model layer is a projection of the database chosen for application use. It
does not attempt to describe every historical artifact, every deprecated column,
or every implementation detail. That is normal. Many mature systems do this.

In this repo, the application intentionally maps views such as `membership` and
`app_log_json` as if they were queryable models, while some lower-level or
deprecated structures are omitted. That means the model layer is useful for app
logic, but incomplete as a database-definition source.

### What Alembic Requires

Alembic does not require every schema object to exist as an ORM model.

Alembic can manage:

- raw SQL via `op.execute(...)`
- explicit table creation and alteration
- data migrations
- view creation and replacement
- trigger and function creation
- extension or comment DDL where appropriate

What Alembic cannot do automatically is infer all of those objects from partial
ORM metadata. That is the key distinction.

### Autogenerate Versus Handwritten Migrations

There are two very different workflows:

- autogenerate: compare SQLAlchemy metadata to a live database and emit a draft
  migration
- handwritten migration: the engineer writes the migration logic explicitly

Autogenerate is limited here for multiple reasons:

- `scheduler/alembic/env.py` currently sets `target_metadata = None`, so there is
  no metadata source configured for comparison
- even if metadata were configured, the application models are not a full schema
  description
- autogenerate generally does not understand views, triggers, functions,
  comments, collations, database creation, or complex data repair logic well
  enough to be trusted as the sole mechanism

So the correct conclusion is not "Alembic cannot manage this database."

The correct conclusion is:

- do not rely on autogenerate as the ownership model
- use handwritten Alembic revisions for nontrivial objects
- treat the ORM as application metadata, not the full production schema contract

## Operational Tooling Boundary

Operational tooling can own workflows that are adjacent to
the database without becoming a second schema authority.

The public repository should document the boundary and the invariants.
The precise command paths, host-local procedures, and operational sequencing
belong in the private deployment docs.

### Provisioning And Deployment

It is coherent for deployment tooling to handle:

- PostgreSQL role creation
- database creation
- schema ownership and grants
- bootstrap execution
- Alembic stamping or upgrade orchestration

Those tasks establish or move the environment into the desired state. They do
not replace the rule that live app schema changes must be represented in
Alembic.

### Credential Rotation

Credential rotation can also be presented through operational tooling. That is a
good interface as long as it remains explicit about the underlying steps.

Rotation still needs to coordinate:

- issuing the new credential
- updating the runtime configuration
- reloading or restarting processes using the old credential
- revoking the old credential after cutover succeeds

The clean interface should expose the workflow clearly, preferably with dry-run
or step-reporting output, rather than hiding the fact that multiple state
transitions occur.

### App-Owned Operational Features

It is reasonable for the application and Admin Panel to expose configuration and
visibility for:

- backup enablement
- a local dump path
- retention count or retention age
- free-disk thresholds for warnings
- backup-age thresholds for warnings
- restore-drill scheduling and result history
- manual backup and restore-drill trigger actions
- DB health and observability status

Those are operational features. They do not weaken Alembic ownership of live
app schema.

## What `.env` Covers And What It Does Not

`.env` gives the application a way to receive credentials and connection
details. In this repo that is handled by the settings layer in
`scheduler/config.py`.

That solves application-side credential delivery.

It does not, by itself, solve:

- creating the PostgreSQL role in the first place
- granting the correct privileges to that role
- coordinating credential rotation
- managing secrets in a dedicated secret store if one is later adopted

Those steps can be handled by deployment or admin tooling. The important
distinction is that a configuration file carries the result of those workflows;
it does not replace the workflows.

## Required Steady State

For a hybrid management model, the steady state must be:

1. Initial deployment may use a documented bootstrap process to create the
   database and import legacy data.
2. That bootstrap result is verified and stamped to a known Alembic baseline.
3. From that point onward, all app-relevant live schema changes go through
   Alembic.
4. Operators may create their own non-app objects outside Alembic only when
   they are isolated and do not affect application behavior.
5. Operational tooling may handle provisioning, backups, restore drills,
   credential rotation, and observability through one clear interface.
6. Runbooks remain the explanatory control surface even when the command path is
   wrapped by operational tooling.

This is the narrowest hybrid model that remains manageable.

## Initial Deployment Workflow

The supported initial deployment flow is:

1. prepare a production-derived dump that satisfies the `003` contract
2. bootstrap an empty target database with `sql/000-init.sh`
3. apply the configured additive relationship-hydration layer
4. verify the resulting schema and data state
5. stamp Alembic to the baseline revision that represents that state
6. verify Alembic ownership with `alembic current` and `alembic_version`
7. start the application and run smoke checks
8. take the first post-deployment backup

The bootstrap worker and the wrapper around it may live in different places.
What matters is that the deployment path performs the full workflow as one
documented operation.

For local validation of that supported flow, the repo provides
`pixi run rehearse-initial-deployment`, which acts as a local contract test for
bootstrap, Alembic ownership verification, and app smoke checks against a
scoped local stack. It is not a replacement for live-host deployment
verification.

## Risks In A Hybrid Model

### Production Drift

If operators make live changes to app-owned objects outside Alembic, the repo no
longer describes production accurately. Future upgrades become unpredictable.

### False Confidence From The ORM

If engineers assume the ORM is the full schema contract, they will miss objects
that still affect production behavior, especially views, functions, triggers,
comments, collations, and data-repair logic.

### Bootstrap Script Reuse

Bootstrap/import scripts are often destructive or assume legacy migration
conditions. Reusing them after go-live creates a real risk of corruption or
conflicting DDL.

### Hidden Behavioral Changes

Out-of-band triggers, defaults, or constraints on app-owned tables can change
application behavior without any code review, migration review, or test signal.

### Split Responsibility Ambiguity

If no one can answer "who owns this object?", the system is not actually
manageable. Hybrid management only works when every object has a clear owner.

## Controls And Gotchas

### Non-Negotiable Rules

- Never apply manual production DDL to app-owned objects outside Alembic.
- Never add operator-managed triggers or rewrite rules to app-owned tables.
- Never let the application depend on an externally managed view or function
  unless it is also brought under Alembic.
- Treat bootstrap SQL as initial-deployment machinery, not as an ongoing live
  migration path.
- Keep the stamped Alembic baseline fixed and documented.

### Safe External Management Pattern

External objects are safest when they:

- live in a separate schema or follow a clear naming convention
- are read-only with respect to app-owned tables
- are not queried by the application
- are documented in runbooks

### Data Migrations Need Extra Care

Several SQL files in this repo perform data repair, normalization, or legacy
reconciliation. Those are often the hardest steps to move into a safe live
migration model.

If a future deployment needs a data rewrite that affects app behavior, it still
belongs in Alembic, but it should be written deliberately and tested against a
copy of realistic data.

### Views And Query Models Need Discipline

Because the app maps some views as models, those views are part of the app
contract. They are not "external" just because they are views. If a view is used
by the app, changes to that view must go through Alembic.

## Practical Decision Rule

When deciding whether an object belongs in Alembic, ask:

1. Does the application query it, write it, or rely on its behavior?
2. Would changing it alter user-visible behavior, correctness, or permissions?
3. Would a fresh production-like rebuild be incomplete or incorrect without it?

If the answer to any of those is yes, Alembic should own it.

## Maintenance Obligations

- Keep the ownership boundary explicit in public and private docs.
- Keep the stamped Alembic baseline documented.
- Move every future app-relevant view, function, trigger, and data migration
  into Alembic, using handwritten revisions where needed.
- Keep operator-managed reporting or maintenance objects isolated from the app
  contract.
- Revisit ownership immediately if an engineer cannot answer who owns a given
  database object.
