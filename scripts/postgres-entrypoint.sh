#!/usr/bin/env bash
set -euo pipefail

# Load variables directly from the app .env format without shell interpolation.
trim() {
  local value=$1
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

load_pg_from_env_file() {
  local file=$1
  local line key value

  if [ ! -f "$file" ]; then
    return
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="$(trim "$line")"
    if [[ -z "$line" || "${line:0:1}" == "#" ]]; then
      continue
    fi
    if [[ "$line" != *"="* ]]; then
      continue
    fi

    key="${line%%=*}"
    value="${line#*=}"
    key="$(trim "$key")"
    value="$(trim "$value")"

    if [ "${#value}" -ge 2 ] && [ "${value:0:1}" = "${value: -1}" ] \
      && { [ "${value:0:1}" = "\"" ] || [ "${value:0:1}" = "'" ]; }; then
      value="${value:1:${#value}-2}"
    fi

    case "$key" in
      PGUSER) PGUSER_FROM_FILE="$value" ;;
      PGPASSWORD) PGPASSWORD_FROM_FILE="$value" ;;
      PGDATABASE) PGDATABASE_FROM_FILE="$value" ;;
    esac
  done < "$file"
}

PGUSER_FROM_FILE="${PGUSER_FROM_FILE:-}"
PGPASSWORD_FROM_FILE="${PGPASSWORD_FROM_FILE:-}"
PGDATABASE_FROM_FILE="${PGDATABASE_FROM_FILE:-}"

load_pg_from_env_file "/app/.env"

PGUSER="${PGUSER:-$PGUSER_FROM_FILE}"
PGPASSWORD="${PGPASSWORD:-$PGPASSWORD_FROM_FILE}"
PGDATABASE="${PGDATABASE:-$PGDATABASE_FROM_FILE}"

if [ -z "$PGUSER" ] || [ -z "$PGPASSWORD" ] || [ -z "$PGDATABASE" ]; then
  echo "ERROR: missing required database credentials. Set PGUSER, PGPASSWORD, PGDATABASE." >&2
  exit 1
fi

export PGUSER
export PGPASSWORD
export PGDATABASE

# Ensure init script and server use container-local defaults.
export POSTGRES_USER="$PGUSER"
export POSTGRES_PASSWORD="$PGPASSWORD"
export POSTGRES_DB="$PGDATABASE"
# During initdb hook execution, postgres is only guaranteed on the local socket.
export PGHOST="${PGHOST:-/var/run/postgresql}"
export PGPORT="${PGPORT:-5432}"

exec /usr/local/bin/docker-entrypoint.sh "$@"
