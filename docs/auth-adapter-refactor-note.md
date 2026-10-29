# Auth Adapter Refactor Note

## Why this note exists

The current test-isolation fix for parallel mock-auth sessions is intentionally small:

- session-scoped mock usernames avoid cross-test collisions
- non-`DEV` PI tests can use distinct groups where practical
- scoped mock `DEV` PI tests use session-local test authority so they do not compete over the single `PrimaryGroupMember` row for `DEV`

That works, but it is still test scaffolding. This note captures the cleaner future direction if maintenance overhead grows.

## Refactor shape

Introduce one request-scoped authorization adapter responsible for answering effective authority questions such as:

- is this user an admin
- which groups does this user manage as PI
- is this user PI of a specific group
- what effective device permissions does this user have

The rest of the app would depend on that adapter instead of mixing direct database lookups and test-only session overlays across multiple call sites.

## Pros

- contains test-only authority handling behind one boundary
- reduces scattered auth conditionals and duplicated role resolution
- makes permission behavior easier to audit and reason about
- gives one place to add caching, diagnostics, and future auth-source changes
- lowers the risk that mock-auth behavior leaks into unrelated scheduler or RBAC logic

## Cons

- larger refactor through core authorization paths
- higher regression risk than the current targeted fix
- adds another layer of indirection to code that is currently easy to trace locally
- still needs a test-only authority source for parallel mock `DEV` PI unless the data model itself changes
- requires disciplined request scoping so caching does not become stale or surprising

## When it becomes worth doing

Do this refactor if one or more of the following become true:

- the test-only PI overlay starts appearing in more than a few authorization call sites
- permission bugs require repeated fixes in multiple places
- new delegated roles or non-database auth sources are added
- mock-auth maintenance starts costing more than a contained refactor would

## Current recommendation

Do not refactor yet.

The present fix is acceptable if:

- the session-local `DEV` PI overlay remains narrowly contained to test scaffolding
- production authorization stays database-backed
- future changes keep the distinction explicit in docs and code review
