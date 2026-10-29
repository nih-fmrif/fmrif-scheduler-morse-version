
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

Running `setup-dotenv.sh` will create an .env file (from .env.sample.local) in the root of the project
with the default values. This file can be modified to set the desired values for
the environment.
The script also replaces the auth-test shared-secret placeholder with a random per-worktree value.

Run `./run-compose.sh --check` to validate env and compose inputs before starting containers.
For network/port semantics when the app runs inside or outside containers, see
[`containerized-postgres.md`](containerized-postgres.md).

`run-compose.sh` also neutralizes Docker Compose `$`-interpolation edge cases by generating a
minimal temp env file for compose metadata (`APP_PORT`, `PGPORT`) while passing the
full raw `.env` only as application config. If you run `docker compose` directly,
values in `.env` containing `$` may still trigger interpolation warnings.

CI and local development use the root `.env` file created from `.env.sample.local`.
`.env.docker` is no longer required for this workflow.

Some useful variables that one might consider setting are listed below.



### Configuration Categories

#### Flask Settings
```env
FLASK_APP=scheduler.app
FLASK_ENV=development
```

#### Server Settings
```env
APP_PORT=5051
# Optional: usually leave unset in local workflows.
# In compose mode, SERVER__SERVER_NAME is derived from APP_PORT.
# SERVER__SERVER_NAME=localhost:5051
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
MAIL__PORT=25
MAIL__USERNAME=test
MAIL__PASSWORD=test
```

### Deployment Specific Configuration

1. **Docker Environment**
   - Uses `.env` (or a copied variant per worktree)
   - Services communicate via Docker network
   - Database host is `postgres`

2. **Deployment/Containerless local development**
   - Uses `.env`
   - Services must be setup/configured independently
