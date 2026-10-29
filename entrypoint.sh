#!/bin/bash
set -e
# override db host/port for containerized execution unless intentionally overridden
export PGHOST="${DB_CONTAINER_HOST:-postgres}"
export PGPORT="${DB_CONTAINER_PORT:-5432}"
container_port="${CONTAINER_APP_PORT:-5051}"

bootstrap_if_missing() {
  if [ ! -x "/sql/000-init.sh" ]; then
    return
  fi

  local db_exists
  db_exists=$(
    PGPASSWORD="$PGPASSWORD" psql \
      -h "$PGHOST" \
      -p "$PGPORT" \
      -U "$PGUSER" \
      -d postgres \
      -tA \
      -c "select 1 from pg_database where datname='${PGDATABASE}'" \
      2>/dev/null || true
  )
  if [ "$db_exists" != "1" ]; then
    >&2 echo "Database ${PGDATABASE} is missing; bootstrapping via /sql/000-init.sh"
    bash /sql/000-init.sh
    return
  fi

  local schema_ready
  schema_ready=$(
    PGPASSWORD="$PGPASSWORD" psql \
      -h "$PGHOST" \
      -p "$PGPORT" \
      -U "$PGUSER" \
      -d "$PGDATABASE" \
      -tA \
      -c "select to_regclass('public.tlkpresearcher') is not null" \
      2>/dev/null || true
  )
  if [ "$schema_ready" != "t" ]; then
    >&2 echo "Database ${PGDATABASE} lacks expected schema; bootstrapping via /sql/000-init.sh"
    bash /sql/000-init.sh
  fi
}

>&2 echo "Postgres is up - starting application"
bootstrap_if_missing
# Run database migrations
alembic upgrade head
# Start the application
export FLASK_APP="${FLASK_APP:-scheduler.app:create_app}"
flask run --host 0.0.0.0 --port "$container_port"
