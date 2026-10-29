# Reviewing the staging changes

PR #5 is based on PR #3 (`tidy-code`). The first ten commits preserve useful
milestones from the original development history. They group adjacent changes,
including the tests that accompanied them. Some changes span more than one
area; the milestones are not independent features that can all be cherry-picked.

## Progression

| Commit | Review focus | Original milestone |
| --- | --- | --- |
| `5b083eb43716` | introduce server-side Entra login and session guards | `60620e9cb2ac` |
| `543fe4aa4341` | add permission administration and mutation checks | `34325fd5847e` |
| `36093dec7a4e` | add audit and issue management with isolated tests | `f9dccbf3ae1c` |
| `73d365f9048e` | implement multi-slot editing and template workflows | `f4654b17bb6a` |
| `b17a71689f83` | unify editors and validate proxy security headers | `4f17cd79c606` |
| `90d353bcd725` | adopt Debian 13 and SQLAlchemy 2 APIs | `487c6e57d006` |
| `9a58edcb7227` | separate logic and route modules | `350920e1a581` |
| `9649b76113c9` | add deployment and database maintenance tooling | `40bee2c23563` |
| `7ec5d97e96c0` | reconcile permissions and administrative issues | `2d02d2de0b6b` |
| `3cd232a929ed` | complete staging review and proxy compatibility | `86e67ea31c37` |

The original hashes refer to the preserved local development history. They are
not additional parents of the published commits. Each commit message records
its original source range so maintainers with that history can investigate why
a change was made.

## Staging checkpoint and later cleanup

The tenth commit is the staging checkpoint, before documentation cleanup.
Compared with the original `86e67ea` snapshot, it deliberately:

- omits `.env.codex.backup` and replaces historical deployment credentials
  with placeholders;
- substitutes synthetic names, identifiers and contact details for client data
  in fixtures and updates matching test expectations;
- fixes CI setup to use the Compose wrapper where supported;
- makes the temporary Debian environment file readable by the container user,
  while its private parent directory protects the copy on the host;
- moves tests of the private installer out of the public repository.

The original byte-identical snapshot remains in the local development branch
and `codex/staging-original-checkpoint`. Do not publish that branch: it retains
the environment backup and original client fixture data.

Later commits organize documentation and remove obsolete scratch notes. Review
those separately from the application changes. The final Debian 13/Pixi package
alignment is still deferred; this series does not claim exact package parity.

## CI failure that prompted the corrections

In Actions run `40766452405`, the unit job failed because installer tests tried
to read files from an absent private submodule. Both Debian jobs failed before
running application tests with `PermissionError` for `/app/.env`. The container
user could not read the mode-0600 temporary file mounted by the wrapper.

Installer tests now belong alongside `install.py` and `host-test.py` in the
private documentation repository, with their own CI job. Public application
checks do not need credentials for that repository.

## Validation and limits

All ten milestones were checked for Python syntax. The latest checkpoint is
also tested through the repository's unit, route, and Debian/runtime wrappers;
current results should be read from CI and the accompanying task report.

The original historical test runs are not recreated merely by preserving a
snapshot. Do not interpret a source commit title such as "validation" as a new
passing result. Full runtime suites have not yet been rerun at every historical
milestone. Dependency availability and runtime setup changed during development,
so reviewing or bisecting an earlier milestone may require its own environment.

The [documentation index](README.md) separates current human guidance from
[agent instructions](agents/README.md) and [historical notes](history/README.md).
