# Configuration Guide

The app reads configuration from `.env` and environment variables through
[`scheduler/config.py`](../scheduler/config.py). Most grouped settings use
`SECTION__VALUE`; database credentials intentionally stay as top-level `PG*`
variables so the app, SQL bootstrap path, and repo tooling share one contract.

## Recommended Local Workflow

1. Generate or refresh `.env` from `.env.sample.local`:

   ```bash
   bash setup-dotenv.sh
   bash setup-dotenv.sh --profile compose
   ```

   Use plain `bash setup-dotenv.sh` for the default host-local PostgreSQL
   contract (`PGHOST=127.0.0.1`, `PGPORT=5432`). Use
   `bash setup-dotenv.sh --profile compose` before any `run-compose.sh`
   workflow so `.env` targets the compose-published ports instead.

2. Start local infrastructure when using the compose profile:

   ```bash
   bash run-compose.sh --no-app
   ```

3. Run the app when needed:

   ```bash
   pixi run serve
   pixi run serve-gunicorn
   ```

`setup-dotenv.sh` rewrites only the managed keys it owns, so unrelated local
entries are preserved. It also derives scope-safe defaults for items such as
`COMPOSE_PROJECT_NAME`, `PGDATABASE`, `SCHEDULER_TEST_DB_NAME`, Mailpit ports,
the session cookie name, and `AUTH_TEST__SHARED_SECRET`.

Most humans do not need to think about `FMRIF_RUNTIME_SCOPE`; the deeper
isolation rules are primarily for agent and parallel-test workflows and are
documented in [agent-guidance-quickstart.md](agent-guidance-quickstart.md).

Supported `setup-dotenv.sh` profiles:

- `host-local-postgres`: local host PostgreSQL defaults (`PGHOST=127.0.0.1`,
  `PGPORT=5432`); this is the default profile
- `compose`: compose-oriented local defaults for `run-compose.sh`
- `default`: backward-compatible alias for the `compose` profile

Use `bash run-compose.sh --check` when you want a quick validation pass over
the current `.env` and compose inputs.

## Local Modes

- `bash run-compose.sh --no-app`
  starts PostgreSQL and Mailpit for host-mode app runs
- `bash run-compose.sh`
  starts the full proxy-aware stack (`nginx + app + postgres + Mailpit`)
- `pixi run serve`
  runs the host-mode Werkzeug server for fast iteration
- `pixi run serve-gunicorn`
  runs the host-mode Gunicorn path when you want behavior closer to deployment

Treat `APP_PORT` as the user-facing application port in every mode. In the full
compose stack, `APP_PORT` belongs to nginx; the Gunicorn app container remains
internal on port `5051`.

Both `pixi run serve` and `pixi run serve-gunicorn` wait for readiness and then
run `scripts/check-edge-security-headers.py`. Outside production the probe
defaults to `http://localhost:${APP_PORT}`. In production it derives its base
URL from `ENTRA__REDIRECT_URI` by stripping `/auth/callback`.

For container-network details and wrapper behavior, see
[containerized-postgres.md](containerized-postgres.md).

## Key Settings

### App and Server

```env
FLASK_APP=scheduler.app:create_app
APP_ENV=development
APP_PORT=5051
# SERVER__SERVER_NAME=localhost:5051
```

- `APP_ENV=development` enables the local-friendly defaults used by the repo
  workflow, including debug behavior and non-secure local session cookies.
- `APP_ENV=production` enables the stricter startup validation path for auth and
  session security.
- `SERVER__SERVER_NAME` is usually best left unset locally unless you
  intentionally need a fixed host value.
- `TEST_BASE_URL` is optional; local Playwright workflows usually derive it from
  `APP_PORT`.

### Database

```env
PGHOST=127.0.0.1
PGPORT=5432
PGUSER=postgres
PGPASSWORD=password
PGDATABASE=fmrif_scheduler
SCHEDULER_TEST_DB_NAME=fmrif_scheduler_test
```

The runtime also exposes explicit database tuning and timeout settings through
`DATABASE__*`, including connection pool sizes, connect timeouts, statement
timeouts, lock timeouts, and slow-query thresholds.

`bash setup-dotenv.sh --profile compose` instead seeds compose-facing host
values such as `PGHOST=localhost` and a compose-published `PGPORT` (typically
`5444` before scope offsets).

Bootstrap dataflow remains:

1. base schema migration
2. snapshot data import (`SQL_SEED_DUMP_FILE`)
3. relationship hydration import

`run-compose.sh` is the supported container entrypoint. It generates the
compose-safe metadata env it needs internally and passes the full `.env` to the
containers as runtime configuration. Direct `docker compose` use is not part of
the supported workflow.

### Mail

```env
MAIL__SERVER=localhost
MAIL__PORT=5446
MAIL__DEFAULT_SENDER=scheduler-local@localhost.localdomain
MAILPIT__PORT=5445
MAILPIT__SMTP_PORT=5446
```

- `MAIL__DEFAULT_SENDER` is required and validated at startup.
- The Admin Panel owns runtime-editable mail content settings such as listserv
  targets and mailing-list catalogs.
- SMTP transport and credentials remain environment-driven.
- In host-mode runs, generated local defaults point the app at host Mailpit.
- In full compose mode, the app container is automatically wired to the
  Mailpit service inside the compose network.

### Auth and External URLs

For Entra/OIDC, the supported deployment model uses the root callback path:

```env
ENTRA__REDIRECT_URI=https://<your-host>/auth/callback
```

Startup validation rejects prefixed callback paths such as
`https://<your-host>/prefix/auth/callback`.

The main production auth inputs are:

- `ENTRA__CLIENT_ID`
- `ENTRA__TENANT_ID`
- `ENTRA__CLIENT_SECRET`
- `ENTRA__DISCOVERY_URL`
- `ENTRA__REDIRECT_URI`
- `ENTRA__SCOPE`

Local mock-auth and Playwright support still depend on `AUTH_TEST__*`; the
shared secret is generated automatically by `setup-dotenv.sh` unless you
override it intentionally.

## Operational Probes In The Main Repo

The repo ships a few deployment-adjacent checks because they are useful for
development and CI:

```bash
pixi run check-db-health -- --json
pixi run check-db-posture -- --json
pixi run rehearse-initial-deployment -- --json
```

- `check-db-health` is the narrow DB-reachability contract.
- `check-db-posture` reads app/admin settings and reports backup, disk, and
  restore-drill posture.
- `rehearse-initial-deployment` is a local contract test for the supported
  bootstrap-plus-Alembic workflow. It uses a scratch DB derived from
  `PGDATABASE` unless you override it.

These commands help validate code and CI behavior. Operator procedures,
host-specific commands, and sensitive deployment detail belong in
`fmrif-scheduler-docs/`.
