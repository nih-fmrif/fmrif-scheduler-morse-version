
## Configuration Guide

Configuration of the application is done using pydantic-settings (in
[scheduler/config.py](../scheduler/config.py)). This is an approach that makes
use of python types to validate the configuration. It is a powerful, concise,
and flexible approach to organizing configuration. It can be overwritten during
development/deployment using .env files or environment variables.

For organized settings, values are grouped into nested config blocks, so most
namespaced settings use `SECTION__VALUE` (for example `CORE__SECRET_KEY`).

Database credentials are intentionally top-level `PG*` variables so they are shared
between application runtime and the SQL bootstrap script without extra mapping.

Bootstrap dataflow uses three stable stages:

- Base schema migration
- Snapshot data import (client-provided dump via `SQL_SEED_DUMP_FILE`)
- Relationship hydration import (CSV mappings into auth/relationship tables)

Running `setup-dotenv.sh` will create an `.env` file (from `.env.sample.local`)
in the root of the project with generated, worktree-specific defaults. It
auto-derives a unique worktree scope from the absolute path, and optionally
accepts `APP_PORT`/`PGPORT`, to derive:
- `COMPOSE_PROJECT_NAME`
- `PGDATABASE` / `SCHEDULER_TEST_DB_NAME`
- `MAILPIT__PORT` (defaults to `PGPORT + 1`, with collision fallback)
- `MAILPIT__SMTP_PORT` (defaults to `PGPORT + 2`, with collision fallback)
- `SESSION__COOKIE_NAME` (and `SESSION__COOKIE_SECURE` is profile-driven by `APP_ENV`)
- `AUTH_TEST__SHARED_SECRET` (randomized token)

This is the preferred local strategy for avoiding port/DB/cookie collisions in concurrent
worktrees; update values in `.env` manually after generation if you need custom overrides.

Run `./run-compose.sh --check` to validate env and compose inputs before starting containers.
For network/port semantics when the app runs inside or outside containers, see
[`containerized-postgres.md`](containerized-postgres.md).

For host-mode development, use `./run-compose.sh --no-app` (postgres + Mailpit).
Playwright integration tasks start their own app server per run, while manual
interactive app work can still use `pixi run serve`. `./run-compose.sh --no-app` performs an
isolated restart (`docker compose down --volumes` then `up`) so local stacks do
not reuse stale state. Use `./run-compose.sh --no-app --resume` for
non-destructive reuse.

`run-compose.sh` also neutralizes Docker Compose `$`-interpolation edge cases by generating a
minimal temp env file for compose metadata (`APP_PORT`, `PGPORT`, `SERVER__SERVER_NAME`)
while passing the full raw `.env` only as application config. If you run `docker compose` directly,
the compose file now fails fast with a required wrapper marker. Use `./run-compose.sh` for
local stacks so compose metadata is generated safely and `$`-bearing values are escaped.

CI and local development use the root `.env` file created from `.env.sample.local`.
`.env.docker` is no longer required for this workflow.

Some useful variables that one might consider setting are listed below.



### Configuration Categories

#### Flask Settings
```env
FLASK_APP=scheduler.app:create_app
APP_ENV=development
```

Profile behavior:
- `APP_ENV=development` enables `AUTH_TEST__ENABLED=true`, `CORE__DEBUG=true`,
  `SESSION__COOKIE_SECURE=false`, and `FLASK_RUN_RELOAD=1`.
- `APP_ENV=production` enforces strict startup checks for auth credentials and
  cookie security before app startup.

#### Server Settings
```env
APP_PORT=5051
# Optional: usually leave unset in local workflows to use request-based hosts.
# Set this when you need a fixed server name.
# Optional: isolate docker-compose resources across worktrees.
# COMPOSE_PROJECT_NAME=scheduler-worktree-name
SERVER__APPLICATION_ROOT=
```

For local development, treat `APP_PORT` as the source of truth for app port wiring.
`run-compose.sh --check` warns when local `SERVER__SERVER_NAME` or `PLAYWRIGHT_BASE_URL`
conflicts with `APP_PORT`.

#### Database Settings
```env
PGHOST=localhost
PGPORT=5444
PGUSER=postgres
PGPASSWORD=password
PGDATABASE=fmrif_scheduler
```

For containerized startup via `run-compose.sh`, PostgreSQL credentials are loaded inside
the container from `.env` by the wrapper script (`scripts/postgres-entrypoint.sh`),
which then sets the image-required `POSTGRES_*` variables.

To run multiple compose stacks on the same host, set `COMPOSE_PROJECT_NAME` so
compose resource names (`scheduler` service containers, volumes, network) stay
isolated. If you leave it unset, `run-compose.sh` derives a default project
name from `<workdir>-<APP_PORT>`.

```env
COMPOSE_PROJECT_NAME=scheduler-worktree-01
```

For Playwright integration tests, local `PLAYWRIGHT_BASE_URL` is optional.
If unset (recommended), local runs derive/sync the port from `APP_PORT`.

### Test Database Override

```env
SCHEDULER_TEST_DB_NAME=fmrif_scheduler_test
```

Use a unique value per worktree or CI job when running suites in parallel.

#### Mail Settings
```env
MAIL__SERVER=localhost
MAIL__PORT=5446
MAIL__DEFAULT_SENDER=scheduler-local@localhost.localdomain
MAIL__USERNAME=test
MAIL__PASSWORD=test
MAILPIT__PORT=5445
MAILPIT__SMTP_PORT=5446
```

`MAIL__DEFAULT_SENDER` is required. Startup fails fast when it is missing or invalid.

In compose mode (`run-compose.sh`), scheduler is auto-configured to use Mailpit
without extra developer setup:
- `MAIL__SERVER=mailpit_app`
- `MAIL__PORT=1025`
- `MAIL__SUPPRESS_SEND=false`
- `MAIL__DEFAULT_SENDER=<configured sender>`

For host-mode app runs (`run-compose.sh --no-app` + `pixi run serve`), generated
`.env` defaults route app SMTP to host Mailpit:
- `MAIL__SERVER=localhost`
- `MAIL__PORT=$MAILPIT__SMTP_PORT`
- `MAIL__SUPPRESS_SEND=false`
- `MAIL__DEFAULT_SENDER=<configured sender>`

### Deployment Specific Configuration

1. **Docker Environment**
   - Uses `.env` (or a copied variant per worktree)
   - Services communicate via Docker network
   - Database host is `postgres`

2. **Deployment/Containerless local development**
   - Uses `.env`
   - Services must be setup/configured independently
