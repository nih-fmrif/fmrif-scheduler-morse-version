#!/bin/bash
set -euo pipefail
# override db host/port for containerized execution unless intentionally overridden
export PGHOST="${DB_CONTAINER_HOST:-postgres}"
export PGPORT="${DB_CONTAINER_PORT:-5432}"
container_port="${CONTAINER_APP_PORT:-5051}"
app_server="${APP_SERVER:-flask}"
python_bin="${PYTHON_BIN:-python3}"

build_gunicorn_command() {
  local bind_addr="0.0.0.0:${container_port}"
  local workers="${GUNICORN_WORKERS:-2}"
  local worker_class="${GUNICORN_WORKER_CLASS:-sync}"
  local timeout="${GUNICORN_TIMEOUT:-120}"
  local threads="${GUNICORN_THREADS:-}"

  local -a command=(
    "$python_bin"
    -m
    gunicorn
    --bind
    "$bind_addr"
    --workers
    "$workers"
    --worker-class
    "$worker_class"
    --timeout
    "$timeout"
    --access-logfile
    -
    --error-logfile
    -
  )

  if [ -n "$threads" ]; then
    command+=(--threads "$threads")
  fi

  command+=(scheduler.wsgi:app)
  printf '%s\n' "${command[@]}"
}

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
"$python_bin" -m alembic upgrade head
# Start the application
case "$app_server" in
  flask)
    export FLASK_APP="${FLASK_APP:-scheduler.app:create_app}"
    exec "$python_bin" -m flask run --host 0.0.0.0 --port "$container_port"
    ;;
  gunicorn)
    mapfile -t gunicorn_command < <(build_gunicorn_command)
    exec "${gunicorn_command[@]}"
    ;;
  *)
    echo "ERROR: APP_SERVER must be one of: flask, gunicorn" >&2
    exit 1
    ;;
esac
