# Code Cleanup Plan

This document is a prompt for a follow-on session after the Debian 13
Flask / Flask-SQLAlchemy / SQLAlchemy upgrade work.

The upgrade itself is done. Treat this as cleanup and modernization work, not
as stack-enablement or cross-version rescue work.

## Baseline

- Target runtime:
  - Flask `3.1.1`
  - Flask-SQLAlchemy `3.1.1`
  - SQLAlchemy `2.0.40`
  - Werkzeug `3.1.3`
- Relevant progress docs:
  - `docs/sqlalchemy-upgrade-progress.md`
  - `docs/sqlalchemy-upgrade-review.md`
  - `docs/debian-12-support-technical-debt.md`
- Latest relevant cleanup commit at the time this plan was written:
  - `12c964a` `Remove execute wrapper and modernize raw SQL paths`
- Verified baseline when this document was written:
  - `pixi run test-unit`
  - `pixi run test-routes`
  - `pixi run test-integration-ci`
  - `pixi run pre-commit`
  - all passed

## Session Setup

For a new session, follow repo agent workflow directly.

1. Choose a fresh `FMRIF_RUNTIME_SCOPE`.
2. Run `bash setup-dotenv.sh`.
3. Reuse an existing healthy compose stack if continuing in the same scope.
4. Otherwise run `bash run-compose.sh --no-app`.
5. Use Pixi tasks for validation, not ad hoc pytest/playwright commands, except
   for narrowly scoped experiments that are explicitly being evaluated.

## Goal

Reduce technical debt that is no longer justified now that the codebase targets
the modern Debian 13 package line directly.

The desired outcomes are:

- smaller and clearer Python modules
- less indirection and fewer compatibility export layers
- better test/runtime maintainability
- faster CI where practical
- no regression in correctness or isolation

## Guardrails

- Do not reintroduce Debian 12 compatibility constraints.
- Prefer incremental commits over one single fully tested and validated commit.
- Keep behavior stable unless a cleanup produces a clear correctness fix.
- Do not rewrite raw SQL just to eliminate SQL; convert only when the result is
  genuinely clearer.
- Keep route behavior, auth/session hardening, and RBAC mutation atomicity
  intact.
- Revalidate the smallest relevant slices first, then expand.

## Workstreams

### 1. Decompose Large Logic Modules

Highest-value targets:

- `scheduler/logic/core.py`
- `scheduler/logic/admin_config.py`

These files still carry too many responsibilities. The main benefit of
decomposition is not package compatibility; it is reducing review surface and
making future changes less risky.

Suggested split directions:

- `core.py`
  - user identity / upsert / migration helpers
  - membership and join-form logic
  - device permission and device/group helper queries
  - device form/update helpers
- `admin_config.py`
  - app settings helpers
  - group/institute mapping parsing and normalization
  - mapping scan/export logic
  - CSV import/export helpers

Recommended approach:

- extract cohesive internal modules first
- keep the public `scheduler.logic` API stable while splitting
- avoid broad renames unless they clearly improve readability

Validation emphasis:

- targeted unit tests for the extracted area
- targeted route/RBAC tests if any route-facing helpers move
- `pixi run pre-commit`

### 2. Reduce Compatibility Export Layers

Targets:

- `scheduler/logic/__init__.py`
- `scheduler/routes/rbac_explorer.py`
- `scheduler/routes/rbac_explorer_query.py`
- `scheduler/routes/rbac_explorer_serialization.py`

These layers exist mainly to preserve older import shapes while code was being
decomposed. That may still be useful, but it should be revisited rather than
assumed.

Questions to answer:

- which re-export surfaces are still buying useful stability?
- which ones only add indirection and make call graphs harder to follow?
- can internal imports move to direct module references without creating a large
  churn tax?

Recommended approach:

- audit actual import sites first
- remove or narrow compatibility re-exports only where the blast radius is
  small and well understood
- prefer explicit imports over wildcard re-export dependence in newly touched
  code

Validation emphasis:

- import/compile smoke
- targeted RBAC route tests if route helper imports change

### 3. Review Remaining Explicit Raw SQL

There is no need to purge all SQL strings. The goal is to leave behind SQL only
where it is the best representation.

Focus on:

- `scheduler/logic/schedule_editor.py`
- `scheduler/logic/templates.py`
- any remaining report-like or bulk-mutation helpers touched during cleanup

Decision rule for each query:

- keep raw SQL if it depends on SQL-native constructs like `generate_series`,
  compact `insert ... select`, or if the ORM rewrite would be less readable
- convert to `select(...)`, `update(...)`, `delete(...)`, or ORM fetches when
  the SQL is only expressing simple entity relationships or scalar existence
  checks

This is a selective cleanup, not a blanket conversion exercise.

### 4. Tighten Types and Data Shapes

Likely targets:

- RBAC explorer/detail payload shaping
- admin-config scan/export rows
- logic helpers still using broad `Dict[str, Any]` or `Any`

Goals:

- reduce accidental key-shape drift
- make refactors safer
- make tests assert against clearer structures

Possible techniques:

- lightweight `TypedDict`
- small dataclasses / named tuples for internal row shapes
- helper-local typed aliases where full models would be overkill

Do not turn this into a “type everything” exercise. Prioritize the code paths
that are currently hardest to reason about.

### 5. Playwright Integration Performance

This is likely one of the highest-value non-functional cleanups.

The integration run that passed on the upgraded stack reported these as the slow
files:

- `tests/playwright/integration/device-ui-interactions.spec.ts`
- `tests/playwright/integration/device-schedule-lateral-contract.spec.ts`

Suggested work:

- split very large spec files into smaller files grouped by behavior
- keep heavy or contention-prone flows clearly tagged
- reduce duplicate setup/navigation where that can be done without making tests
  harder to read
- prefer page-object/helper reuse over giant omnibus specs

Success metric:

- lower wall-clock time for `pixi run test-integration-ci`
- no increase in test flakiness

### 6. Evaluate Pytest Parallelization Carefully

`pytest-xdist` is already present in the lockfile, but it is not currently part
of the standard Pixi pytest tasks.

This should be treated as an evaluation task, not as an automatic upgrade.

Current facts:

- suite wrappers already isolate DB/Mailpit/runtime resources by scope
- same-suite plus same-scope concurrency is intentionally blocked by an
  advisory lock
- docs already note that tests can still contend if parallel workers mutate the
  same business rows
- coverage-file collision across parallel runs was already fixed at the wrapper
  level with suite-scoped `COVERAGE_FILE`

What this implies:

- xdist is more plausible for pure or mostly pure unit tests
- xdist is not obviously safe for route tests under the current shared mutable
  suite database model
- enabling xdist blindly for `test-routes` is likely to create noisy conflicts
  or nondeterminism

Recommended evaluation order:

1. Benchmark the current baseline:
   - `pixi run test-unit`
   - `pixi run test-routes`
2. Run an experiment on a safe subset of unit tests first.
3. If promising, add an opt-in task such as `test-unit-xdist` before changing
   the default task.
4. Only consider route-test xdist after designing worker-aware isolation
   explicitly.

Questions that must be answered before enabling xdist by default:

- do DB-using unit tests need worker-specific databases?
- do route tests need worker-specific route-template/runtime DB names?
- do any fixtures assume one in-process global ordering?
- does coverage aggregation stay correct under the chosen xdist mode?
- is the speedup real enough to justify the extra complexity?

Practical recommendation:

- yes, xdist is worth considering
- start with unit-test experiments only
- do not enable it for route tests unless worker-specific isolation is designed
  and validated

### 7. CI and Test-Task Ergonomics

Once the above is clearer, revisit whether the test tasks should expose more
useful opt-in variants:

- split Playwright integration tasks by area or browser when useful
- optionally add a non-default xdist task for suitable unit subsets
- keep the default tasks conservative and deterministic

The default developer workflow should remain simple. Advanced performance
variants should be additive, not replacements, until they prove reliable.

## Suggested Execution Order

1. Playwright performance cleanup
2. `core.py` decomposition
3. `admin_config.py` decomposition
4. compatibility export reduction
5. selective type tightening
6. xdist evaluation after the module/test surfaces are cleaner

This order keeps the highest payoff items near the front and avoids mixing test
parallelization experiments with a still-moving internal structure.

## Suggested Commit Strategy

Prefer a trajectory like this:

1. split one large module without behavior changes
2. validate targeted tests and commit
3. split the next module and commit
4. split one large Playwright file and commit
5. run broader validation
6. run xdist experiments in a separate exploratory commit or branch

Do not combine module decomposition, Playwright splitting, and xdist changes in
one commit.

## Validation Expectations

At minimum for each cleanup slice:

- the narrowest relevant `pixi run test-unit` or `pixi run test-routes` subset
- `pixi run pre-commit`

At the end of any broad cleanup round:

- `pixi run test-unit`
- `pixi run test-routes`
- run `pixi run test-integration-ci` whenever Playwright files, route behavior,
  or shared test infrastructure changed

## Deliverable For The Follow-On Session

The next session should:

- choose one cleanup workstream
- make one bounded improvement
- record progress in a markdown file if the work spans multiple commits
- keep the branch history readable
- stop short of speculative churn

The standard for success is not “make the code look newer.” The standard is:

- less indirection
- clearer ownership
- faster feedback where justified
- no regression in determinism or correctness
