## Containerized PostgreSQL With `run-compose.sh`

This project uses one `.env` contract for both host and container workflows:

- `PGHOST`
- `PGPORT`
- `PGUSER`
- `PGPASSWORD`
- `PGDATABASE`

These `PG*` variables are read by the application and by `sql/000-init.sh`.
The official Postgres image still requires `POSTGRES_*` during container startup, so
the wrapper at `scripts/postgres-entrypoint.sh` derives those from `PG*` internally.

For local port wiring, prefer these canonical values:

- `APP_PORT`: host port to reach the app
- `PGPORT`: host port to reach Postgres

To keep multiple local stacks isolated, also set:

- `COMPOSE_PROJECT_NAME`: unique compose resource prefix per worktree/job.
  If omitted, `run-compose.sh` derives `<workdir>-<APP_PORT>`.

Other local URL settings should normally be unset unless intentionally overriding.

## Why this is split

The bootstrap path follows a fixed three-step dataflow:
- Base schema migration
- Snapshot data import
- Relationship hydration import

`run-compose.sh` writes two temporary env files because compose interpolation is
not the same as application configuration:

- **Compose interpolation env** (internal): only safe metadata keys
  (`APP_PORT`, `PGPORT`) with escaped `$`.
- **Runtime app/env file** (mounted into containers): full raw `.env` with all values.

This keeps `.env` easy to manage while avoiding compose interpolation surprises.

## Host vs Container Modes

### Mode A: App and DB both run in compose (default)

- Start with:
  - `bash run-compose.sh`
- Keep `.env` focused on host-facing values:
  - `PGHOST=localhost` for host tools and direct local app runs
  - `PGPORT=<published host postgres port>` (default: `5444`)

In this mode:

- Containerized Postgres listens on container port `5432`.
- Compose publishes Postgres to host port from `PGPORT` (for example `5444`).
- Scheduler container DB settings are overridden by compose:
  - `PGHOST=postgres`
  - `PGPORT=5432`
- `sql/000-init.sh` runs inside the Postgres container and uses container-local
  connection defaults.

### Mode B: App runs on host (containerless)

- Point the app at whichever Postgres endpoint the host can reach.
- Typical local values:
  - `PGHOST=localhost`
  - `PGPORT=<host db port>` (for example `5432` for native Postgres, `5444`
    for compose-published Postgres)
- Start with local app runner, for example:
  - `APP_PORT=5051 pixi run serve`

### Mode C: App runs in other container tooling

When the app runs in a different container runner, make sure DB connectivity is
resolved through that container network:

- `PGHOST` must be a reachable host for the app container (`postgres`, service name,
  or network alias).
- `PGPORT` must be the Postgres port from the app container’s perspective
  (`5432` when talking to the same compose network).
- `.env` can remain shared, but host runner values (`localhost`) are usually not
  valid from inside another container.

## Common `.env` gotchas

1. **`PGPORT` means different things by mode**
   - In containerized startup this is mainly the host-mapped publish port for the
     local Postgres container.
   - Inside containers, the server port is usually `5432`.
2. **Compose resource isolation**
   - For concurrent stacks, use a unique `COMPOSE_PROJECT_NAME` so container/volume
     names do not collide.
3. **`$` in values**
   - `run-compose.sh` avoids compose interpolation by using a generated env file.
   - Running `docker compose` directly against `.env` can still emit warnings for
     unescaped `$` values.
4. **Container wrapper is required**
   - Keep `POSTGRES_*` out of `.env` and rely on `PG*`.
   - Use `scripts/postgres-entrypoint.sh` only for the compose path.
5. **Seed/init assumptions**
   - `sql/000-init.sh` expects DB credentials (`PGHOST`, `PGPORT`, `PGUSER`,
     `PGPASSWORD`, `PGDATABASE`) to be present in its runtime environment.
6. **Health + readiness**
   - The `postgres` service starts on `5432`; init scripts and app startup are
     gated by compose health checks and service dependencies.
7. **Avoid duplicate local app-port declarations**
   - Keep `APP_PORT` authoritative.
   - `SERVER__SERVER_NAME` is derived in compose.
   - `PLAYWRIGHT_BASE_URL` local port is auto-synced from `APP_PORT` in test config.
   - `run-compose.sh --check` warns if local overrides conflict with `APP_PORT`.

## Quick checks

- Validate compose wiring:
  - `bash run-compose.sh --check`
- Verify a host-mode containerless run:
  - `PGHOST=localhost PGPORT=<host db port> PGPASSWORD=... PGUSER=... PGDATABASE=... APP_PORT=5051 pixi run serve`
- If startup fails with missing seed or mount errors, rerun after ensuring `/app/.env`
  is mounted and contains all required `PG*`.
