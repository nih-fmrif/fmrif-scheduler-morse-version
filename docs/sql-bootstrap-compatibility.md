# SQL Bootstrap Compatibility with Old Production Data

## Goal

The current SQL bootstrap must remain compatible with data rooted in the old
application state so future seed refreshes do not require another deep manual
reconstruction.

There are two distinct compatibility questions:

1. Is the seed data shape compatible with the old `001-schema.sql` import stage?
2. Is the seed data *stage* compatible with the later data migrations,
   especially `015-reseachers.sql`, `018-invalidate-old-researchercodes.sql`,
   and `900-import-new-data.sql`?

This document defines the supported answers for both.

## Supported `003` dump contract

`sql/003-import-data.sql` or any replacement supplied via
`SQL_SEED_DUMP_FILE` must satisfy all of the following:

- It must be a data-only import targeting the old `001` schema shape.
- It must use explicit rows for `tbltemplates` and `tbltemplate`.
- It must not rely on the old `template_fill` rule.
  - `sql/000-init.sh` loads the seed under `session_replication_role = replica`.
  - That disables rules and triggers during the seed import.
- It must not contain post-current-schema tables created by later migrations in
  this repository.

For old-production compatibility, the canonical example remains the original
old-repo `003-import-data.sql`: it dumps `tbltemplates`, `tbltemplate`,
`tlkpresearcher`, `tlkpdept`, `tlkpscanner`, and `tblsched` directly in
old-schema column shape.

## Supported researcher-code stages

The current chain supports both of these seed stages:

### `pre-018`

- `tlkpresearcher.researchercode` values do not yet end in `"[OLD]"`.
- `tbltemplate.researchercode` and `tblsched.researchercode` also use the
  unsuffixed code.
- `018-invalidate-old-researchercodes.sql` will suffix the researcher codes.
- Because `015-reseachers.sql` adds `ON UPDATE CASCADE` researcher FKs to
  `tblsched` and `tbltemplate`, the rooted `"[OLD]"` values then propagate into
  those tables as part of the normal chain.

### `post-018`

- `tlkpresearcher.researchercode` values already end in `"[OLD]"`.
- `tbltemplate.researchercode` and `tblsched.researchercode` already refer to
  the suffixed value.
- `018-invalidate-old-researchercodes.sql` is intentionally idempotent, so the
  current chain now accepts this stage without double-suffixing researcher ids.

### Unsupported mixed stage

Mixed-stage dumps are not supported.

Examples:

- `tlkpresearcher` is post-`018` but `tbltemplate` still references unsuffixed
  researcher codes.
- `tlkpresearcher` is pre-`018` but `tbltemplate` already references
  suffixed codes.

Those dumps must be normalized before they are used as `SQL_SEED_DUMP_FILE`.

## Migration audit

### `013-null-and-zero-normalization.sql`

Operationally safe for both supported stages.

- It normalizes empty strings to `NULL` for researcher references.
- It tightens defaults and not-null constraints.
- It does not depend on `"[OLD]"` stage.

### `015-reseachers.sql`

Safe for both supported stages, assuming the dump is still `001`-shape
compatible.

- It backfills missing `tlkpresearcher` rows from `tblsched` and `tbltemplate`.
- It adds researcher foreign keys with `ON UPDATE CASCADE`.
- This is the migration that makes the later `018` suffix propagation visible in
  schedule/template rows for pre-`018` seeds.

### `018-invalidate-old-researchercodes.sql`

This is the critical stage-sensitive migration.

- It now runs idempotently:
  - pre-`018` seed: suffixes researchers once
  - post-`018` seed: no-op
- This avoids maintaining two bootstrap paths solely because of the old suffix
  migration.

### `900-import-new-data.sql`

This is an additive relationship-hydration layer, not part of the old snapshot.

It is not an authentication layer.

Authentication is handled by Entra. The additive layer hydrates current
authorization and operational relationship tables after the legacy snapshot has
been imported.

Default behavior:

- Keep it enabled for old-schema production-like dumps.
- It hydrates current auth/RBAC relationship tables from CSV mappings after the
  old snapshot import and schema migrations.

Collision strategy:

- If your source dump is old-schema-only: leave `900` enabled.
- If your source import already includes equivalent current relationship data,
  disable `900` with:

```bash
SQL_ADDITIVE_LAYER_FILES=
```

- If you need a custom hydration layer, set `SQL_ADDITIVE_LAYER_FILES` to one or
  more explicit SQL files instead of using the default `900-import-new-data.sql`.

Operational rule:

- Treat the additive layer as a separate authority decision.
- The old snapshot provides historical scanner/template/schedule data.
- The additive layer provides current relationship hydration for the current app.

Supported initial-deployment role:

- a production-derived `003`-contract dump supplies the rooted legacy snapshot
- `900-import-new-data.sql` may supply the starting authorization relationships
  for the new application
- after deployment, the RBAC and Admin Panel surfaces become the live
  management path for those relationships

## Recommended import modes

### Generated rooted subset for normal local/test work

Use the checked-in subset or regenerate it from the old compatibility database:

```bash
python scripts/generate-rooted-template-seed.py --researcher-stage pre-018
python scripts/generate-rooted-template-seed.py --researcher-stage post-018
```

This is the normal fast path for local development and route/integration tests.

### Fresh production-derived dump

A fresh production-derived seed is supported when it satisfies the `003`
contract above.

The client must choose one of:

- export or transform the dump to `pre-018` stage
- export or keep the dump in `post-018` stage

The client should not need a separate current bootstrap path for those two
choices. The current chain supports both stages directly.

What still matters is consistency:

- choose one stage
- keep `tlkpresearcher`, `tbltemplate`, and `tblsched` aligned to that stage
- keep the dump in old-schema column shape

## Compatibility verification guard

Two new artifacts exist so this does not rely on memory:

- [verify-old-bootstrap-compat.py](../scripts/verify-old-bootstrap-compat.py)
- [test_old_bootstrap_compat.py](../tests/unit/test_old_bootstrap_compat.py)

What the verifier does:

1. bootstraps the old repository into a compatibility database
2. generates rooted subset seeds in both `pre-018` and `post-018` modes
3. boots the current chain against each generated seed
4. asserts:
   - templates load
   - template cells load
   - every template remains a full `168`-slot grid
   - rooted `"[OLD]"` researchers survive bootstrap
   - rooted `'(none)'` template cells survive bootstrap

Example direct run:

```bash
export OLD_BOOTSTRAP_PGHOST=127.0.0.1
export OLD_BOOTSTRAP_PGPORT=6543
export OLD_BOOTSTRAP_PGUSER=postgres
export OLD_BOOTSTRAP_PGPASSWORD=password

export TARGET_PGHOST=127.0.0.1
export TARGET_PGPORT=5547
export TARGET_PGUSER=postgres
export TARGET_PGPASSWORD=postgres

python scripts/verify-old-bootstrap-compat.py
```

Pixi wrapper:

```bash
pixi run test-old-bootstrap-compat
```

Fast path when the old compatibility DB is already bootstrapped:

```bash
OLD_BOOTSTRAP_SKIP_REBUILD=true pixi run test-old-bootstrap-compat
```

The verifier supports separate endpoints:

- `OLD_BOOTSTRAP_*` controls the source Postgres used to bootstrap/query the old repo data
- `TARGET_*` controls the target Postgres used for scratch current-chain verification DBs

If those variables are unset, the script falls back to the ordinary `PG*`
environment values.

Pytest wrapper:

```bash
OLD_BOOTSTRAP_COMPAT_RUN=true pytest tests/unit/test_old_bootstrap_compat.py -q
```

That test is opt-in because it is intentionally heavier than the normal route
or unit suites.

## Long-term maintenance rule

When any of these change:

- `sql/000-init.sh`
- `sql/003-import-data.sql`
- `sql/013-null-and-zero-normalization.sql`
- `sql/015-reseachers.sql`
- `sql/018-invalidate-old-researchercodes.sql`
- `sql/900-import-new-data.sql`
- `scripts/generate-rooted-template-seed.py`

run the compatibility verifier again.

If it fails, either:

- fix the current chain to restore rooted compatibility, or
- explicitly document the newly unsupported old-data pattern and why it is no
  longer supported.

## Fixture data in the public repository

The published fixtures use synthetic user identifiers, names, and contact
details while retaining the relationships needed by the tests. Extracting
fixtures from a client database can reintroduce personal data. Review and
anonymize generated output before committing it; keep original dumps private.
