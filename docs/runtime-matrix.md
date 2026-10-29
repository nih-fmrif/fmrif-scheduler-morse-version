# Runtime Matrix

## Why Two Paths Exist

The repository uses two complementary runtime paths on purpose:

- Pixi-first for daily development speed, local convenience, and fast feedback.
- Debian system-package verification for the near-term deployment reality on likely host systems.

Pixi remains the primary developer and agent workflow. It is faster to iterate in, easier to debug, and exposes the most useful commands as repo tasks. Debian verification exists to catch issues that only appear once the app is run against distro-packaged Python and system libraries.

## What Debian Verification Covers

The Debian runtime matrix currently targets:

- Debian `12.13`
- Debian `13.1`

Those runs exercise the app through Compose using Debian-packaged dependencies, nginx, PostgreSQL, Mailpit, migrations, and mock-auth Playwright integration flows.

This is not a perfect substitute for a real bare-metal deployment with systemd and service-user permissions. It does not fully prove host-level installation, host filesystem ownership, or all package-drift scenarios. It does catch a large portion of real deployment errors early, including dependency packaging differences, framework/API drift, startup issues, migration failures, proxy behavior, and UI flows against the packaged runtime.

## CI Shape

GitHub CI now uses three layers:

1. Fast Pixi-managed tests for the main developer feedback loop.
2. Debian runtime smoke checks on `12.13` and `13.1`.
3. Debian runtime Playwright integration checks on `12.13` and `13.1`.

The Debian Playwright job runs Chromium only. Browser-engine coverage is already provided by the primary Pixi integration job, while the Debian matrix is focused on runtime packaging differences.

## Local Commands

Pixi remains the main entrypoint:

```bash
pixi run test-unit
pixi run test-routes
pixi run test-integration
DEBIAN_VERSION=12.13 pixi run test-debian-smoke
DEBIAN_VERSION=12.13 pixi run test-debian-integration
DEBIAN_VERSION=13.1 pixi run test-debian-smoke
DEBIAN_VERSION=13.1 pixi run test-debian-integration
```

The Debian tasks bring up the Compose stack with the Debian runtime image, run the requested verification, and tear the stack down automatically.

## Practical Guidance

- Use Pixi-first tasks for normal implementation work.
- Use the Debian tasks when changing runtime dependencies, startup/config loading, auth/session behavior, nginx behavior, or database/bootstrap code.
- Treat Debian failures as deployment-relevant even if the Pixi path remains green.
