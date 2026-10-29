# Scheduler app

## Documentation

For detailed documentation, please refer to:
- [Project Documentation](docs/README.md)

## Setup

### Configure the application

The application is configured using `.env` files (see a more detailed
configuration guide in
[docs/configuration-guide.md](docs/configuration-guide.md)). Run the following
command to get started quickly. Change sensitive values when ready to deploy.

```
bash setup-dotenv.sh
```

## Worktree quickstart

From a fresh worktree:

1. `bash setup-dotenv.sh`
2. Set `APP_PORT` and `PGPORT` for your local environment
3. Run either:
   - `APP_PORT=5051 pixi run serve` for local non-container development
   - `bash run-compose.sh` for containerized development
4. For a dry-run sanity check before startup:
   - `bash run-compose.sh --check`

### Parallel worktree pattern

For multiple concurrent worktrees, set a unique scope and derive all host-level
ports/databases from it:

```bash
WORKTREE_SCOPE=alice
export APP_PORT=5051
export PGPORT=5444
export COMPOSE_PROJECT_NAME="scheduler-${WORKTREE_SCOPE}"
export PGDATABASE="fmrif_scheduler_${WORKTREE_SCOPE}"
export SCHEDULER_TEST_DB_NAME="fmrif_scheduler_test_${WORKTREE_SCOPE}"
```

- `APP_PORT` isolates web listeners.
- `PGPORT` isolates Postgres host listeners and Docker published ports.
- `COMPOSE_PROJECT_NAME` isolates compose containers/volumes/network names.
  If unset, `run-compose.sh` derives a default from `<workdir>-<APP_PORT>`.
- `SCHEDULER_TEST_DB_NAME` isolates pytest/route test schema usage.

Run the same commands as above with those exports in place.

## Environment Variables

The application uses PostgreSQL connection parameters that can be configured in two ways:

### Using .env file (recommended for development)
Create a `.env` file in the project root with these variables:
```
APP_PORT=5051
PGHOST=localhost
PGPORT=5444
PGUSER=postgres
PGPASSWORD=replace-with-pgpassword
PGDATABASE=fmrif_scheduler
```

### Using environment variables (recommended for production)
If you prefer to set environment variables directly (which will override .env values):
```bash
export APP_PORT=5051
export PGHOST=localhost
export PGPORT=5444
export PGUSER=postgres
export PGPASSWORD=replace-with-pgpassword
export PGDATABASE=fmrif_scheduler
```

### Important Note on PostgreSQL Variables
- `PG*` variables are the canonical DB inputs for this repo (app + bootstrap scripts).
- The dockerized postgres service now uses `/usr/local/bin/postgres-entrypoint.sh` to map `PG*` to `POSTGRES_*` for the official image internally.

When using Docker through `run-compose.sh`, set only `PG*` in `.env`.
`run-compose.sh` now validates and feeds a generated compose env file so `$` in values can remain unquoted for Docker metadata interpolation.
For additional container/host Postgres semantics, read [docs/containerized-postgres.md](docs/containerized-postgres.md).

## Install/Run the application

Local dev dependencies are declared in `pyproject.toml` and managed with Pixi.
From the project root:
```bash
pixi install
APP_PORT=5051 pixi run serve
```

If you prefer `uv`, it can be used directly for the Python environment, but
repository workflows and CI are aligned on Pixi tasks.

## Local development/testing

### Local setup (host mode)

1. Start PostgreSQL server however you wish, the following could work assuming you are using the correct postgres variables from .env:
```bash
docker run --name postgres_db \
  -e POSTGRES_PASSWORD=$PGPASSWORD \
  -e POSTGRES_USER=$PGUSER \
  -e POSTGRES_DB=$PGDATABASE \
  -p $PGPORT:5432 \
  --rm \
  -v pgdata:/var/lib/postgresql/data \
  postgres:15
```

2. Initialize the database (use DROP_DB=true to reset existing database):
   1. base schema migration
   2. snapshot data import from seed dump
   3. relationship hydration import from CSV mappings
```bash
DROP_DB=true bash sql/000-init.sh
```

3. Run the application:
```bash
pixi install
APP_PORT=5051 pixi run serve
```

### Containerized setup

Dependencies:
- Docker with Compose plugin

The following will run a containerized PostgreSQL database, initialize the
database schema, and start the application:

```
bash run-compose.sh
```

This will start:
- PostgreSQL on host port `$PGPORT` (default: `5444`)
- Scheduler application on host port `$APP_PORT` (default: `5051`)


### Backend testing

Run unit and route tests with the Pixi tasks defined in `pixi.toml`:

```bash
AUTH_TEST__ENABLED=true AUTH_TEST__SHARED_SECRET=local-test-secret pixi run test-unit
AUTH_TEST__ENABLED=true AUTH_TEST__SHARED_SECRET=local-test-secret pixi run test-routes
```

If you prefer a compact Pixi flow for direct commands, run:

```bash
AUTH_TEST__ENABLED=true AUTH_TEST__SHARED_SECRET=local-test-secret pixi run test-unit
```

### Frontend testing

Dependencies:
- Node.js 18+ (for testing frontend)

1. Install Node.js dependencies:
```bash
pixi run install-js
```

1. Install Playwright browsers:
```bash
pixi run install-playwright
```

1. Run tests:
```bash
pixi run test-integration
```
