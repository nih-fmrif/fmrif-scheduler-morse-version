
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

Running `setup-dotenv.sh` updates `.env` (from `.env.sample.local`)
in the root of the project with scope-aware defaults. It uses
`FMRIF_RUNTIME_SCOPE` (or defaults to `default`) and optionally accepts `APP_PORT`/`PGPORT`,
to derive:
- `COMPOSE_PROJECT_NAME`
- `PGDATABASE` / `SCHEDULER_TEST_DB_NAME`
- `MAILPIT__PORT` (defaults to `PGPORT + 1`, with collision fallback)
- `MAILPIT__SMTP_PORT` (defaults to `PGPORT + 2`, with collision fallback)
- `SESSION__COOKIE_NAME` (and `SESSION__COOKIE_SECURE` is profile-driven by `APP_ENV`)
- `AUTH_TEST__SHARED_SECRET` (randomized token)

This is the preferred local strategy for avoiding port/DB/cookie collisions across scopes.
`setup-dotenv.sh` rewrites only managed keys, so unrelated entries are preserved.

Run `./run-compose.sh --check` to validate env and compose inputs before starting containers.
For network/port semantics when the app runs inside or outside containers, see
[`containerized-postgres.md`](containerized-postgres.md).

For host-mode development, use `./run-compose.sh --no-app` (postgres + Mailpit).
Playwright integration tasks start their own app server per run, while manual
interactive app work can still use `pixi run serve`. `./run-compose.sh --no-app` performs an
isolated restart (`docker compose down --volumes` then `up`) so local stacks do
not reuse stale state. Use `./run-compose.sh --no-app --resume` for
non-destructive reuse.

Host-mode `pixi run serve` uses Flask/Werkzeug for a fast edit-refresh loop.
When you want host-side serving closer to deployment behavior without the full
compose stack, use `pixi run serve-gunicorn`. Both startup paths now wait for
local readiness and then run `scripts/check-edge-security-headers.py`. In
production, that probe derives its target from `ENTRA__REDIRECT_URI` by
removing `/auth/callback`; outside production it falls back to
`http://localhost:${APP_PORT}`.

For proxy-aware local validation, use `./run-compose.sh` so requests flow through
nginx before reaching the app server. In that mode, `APP_PORT` is owned by nginx
and the Gunicorn-backed app container remains internal to the compose network.
The full compose stack defaults to `linux/amd64`, and the app container builds
its Python environment from the shared repository `pixi.toml` after narrowing
the copied in-image manifest to `linux-64`. That keeps host and container
workflows on one tracked dependency manifest while still exercising the x86
Linux solve path in Docker.

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
# SERVER__SERVER_NAME=localhost:5051
# Optional: isolate docker-compose resources across scopes.
# COMPOSE_PROJECT_NAME=scheduler-scope-name
```

For local development, treat `APP_PORT` as the source of truth for app port wiring.
`run-compose.sh --check` warns when local `SERVER__SERVER_NAME` or `TEST_BASE_URL`
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
isolated. If you leave it unset, `run-compose.sh` appends the scope to a stable base project
prefix.

```env
COMPOSE_PROJECT_NAME=scheduler-<scope>
```

For Playwright integration tests, local `TEST_BASE_URL` is optional.
If unset (recommended), local runs derive/sync the port from `APP_PORT`.

Optional static asset cache-busting override:

```env
STATIC_ASSET_VERSION=<deploy-id-or-git-sha>
```

If unset, the app falls back to the current git SHA for top-level static asset
URLs.

For Entra/OIDC, root-only deployment is now the supported model. Set:

```env
ENTRA__REDIRECT_URI=https://<your-host>/auth/callback
```

Startup validation rejects prefixed callback paths such as
`https://<your-host>/prefix/auth/callback`.

Default CSP reporting uses `report-to csp-endpoint` plus
`Reporting-Endpoints: csp-endpoint="/csp-report"`. Reports posted to
`/csp-report` are redacted before storage, written to the database, and
surfaced in the Admin Panel.

### Test Database Override

```env
SCHEDULER_TEST_DB_NAME=fmrif_scheduler_test
```

Use `FMRIF_RUNTIME_SCOPE` to isolate suites per run.

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
The Admin Panel now owns the runtime-editable mail content settings:
- listserv target
- effective default sender override
- mailing-list catalog

SMTP transport and credentials remain environment-driven.

In compose mode (`run-compose.sh`), scheduler is auto-configured to use Mailpit
without extra developer setup:
- `MAIL__SERVER=mailpit_app`
- `MAIL__PORT=1025`
- `MAIL__SUPPRESS_SEND=false`
- `MAIL__DEFAULT_SENDER=<configured sender>`
- `APP_SERVER=gunicorn`
- `APP_PORT` terminates at the local nginx service, which forwards the expected
  `X-Forwarded-*` headers to the scheduler container

For host-mode app runs (`run-compose.sh --no-app` + `pixi run serve`), generated
`.env` defaults route app SMTP to host Mailpit:
- `MAIL__SERVER=localhost`
- `MAIL__PORT=$MAILPIT__SMTP_PORT`
- `MAIL__SUPPRESS_SEND=false`
- `MAIL__DEFAULT_SENDER=<configured sender>`

### Deployment Specific Configuration

1. **Docker Environment**
   - Uses `.env` (or a copied variant when scope-specific settings are managed separately)
   - Services communicate via Docker network
   - Database host is `postgres`

2. **Deployment/Containerless local development**
   - Uses `.env`
   - Services must be setup/configured independently
