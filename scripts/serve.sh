#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/runtime-scope.sh"

env_file="${ENVFILE:-.env}"

trim() {
  local value=$1
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

load_env_file() {
  local file=$1
  local line key value

  while IFS= read -r line || [ -n "$line" ]; do
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
    if [[ -z "$key" ]]; then
      continue
    fi

    if [[ -n "${!key+_}" ]]; then
      continue
    fi

    if [ "${#value}" -ge 2 ] && [ "${value:0:1}" = "${value: -1}" ] \
      && { [ "${value:0:1}" = '"' ] || [ "${value:0:1}" = "'" ]; }; then
      value="${value:1:${#value}-2}"
    fi

    printf -v "$key" '%s' "$value"
  done < "$file"
}

validate_port() {
  local candidate=$1
  local name=$2
  if [[ ! "$candidate" =~ ^[0-9]+$ ]] || (( candidate < 1 || candidate > 65535 )); then
    echo "ERROR: invalid $name: $candidate" >&2
    exit 1
  fi
}

validate_non_negative_int() {
  local value=$1
  local name=$2
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    echo "ERROR: ${name} must be a non-negative integer: ${value}" >&2
    exit 1
  fi
}

wait_for_local_http_ready() {
  local url=$1
  local timeout_seconds=${2:-60}
  local deadline=$((SECONDS + timeout_seconds))

  while (( SECONDS < deadline )); do
    if [ -n "${SERVER_PID:-}" ] && ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "ERROR: app server exited before readiness probe succeeded." >&2
      return 1
    fi

    if curl --silent --fail --output /dev/null --max-time 2 "$url"; then
      return 0
    fi

    sleep 1
  done

  echo "ERROR: timed out waiting for local app readiness at $url" >&2
  return 1
}

stop_server() {
  if [ -z "${SERVER_PID:-}" ]; then
    return 0
  fi

  if kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}

forward_signal() {
  local signal=$1
  if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill -s "$signal" "$SERVER_PID" 2>/dev/null || true
  fi
}

persist_scope_metadata_if_present() {
  if [ -z "${RUNTIME_SCOPE_FILE:-}" ] || [ ! -f "$RUNTIME_SCOPE_FILE" ]; then
    return 0
  fi
  runtime_scope_write_metadata "$RUNTIME_SCOPE_FILE"
}

cleanup_scope_metadata() {
  unset RUNTIME_SCOPE_HOST_APP_PID
  persist_scope_metadata_if_present || true
}

run_edge_header_gate() {
  local script_path="${SCRIPT_DIR}/check-edge-security-headers.py"

  if ! python3 "$script_path"; then
    echo "ERROR: final edge security header validation failed. The app server was stopped because the served response is missing required security headers or the wrong edge URL is configured." >&2
    echo "  Production target is derived from ENTRA__REDIRECT_URI by removing /auth/callback." >&2
    echo "  Outside production, the probe falls back to http://localhost:${APP_PORT}." >&2
    return 1
  fi
}

build_gunicorn_command() {
  local bind_host="${APP_BIND_HOST:-127.0.0.1}"
  local bind_addr="${bind_host}:${APP_PORT}"
  local workers="${GUNICORN_WORKERS:-2}"
  local worker_class="${GUNICORN_WORKER_CLASS:-sync}"
  local timeout="${GUNICORN_TIMEOUT:-120}"
  local threads="${GUNICORN_THREADS:-}"

  local -a command=(
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

coalesce_session_cookie_name() {
  local base_cookie="${1:-}"
  local scope="${RUNTIME_SCOPE:-default}"
  if [ -z "${base_cookie}" ]; then
    base_cookie="dsid-${scope}"
  fi

  if [ "${scope}" = "default" ] || [[ "$base_cookie" == *"-${scope}" ]]; then
    printf '%s' "$base_cookie"
    return 0
  fi

  printf '%s-%s' "$base_cookie" "$scope"
}

if [ ! -f "$env_file" ]; then
  echo "ERROR: $env_file was not found. Run setup-dotenv.sh or create it manually." >&2
  exit 1
fi

load_env_file "$env_file"
runtime_scope_derive
runtime_scope_load_metadata "$RUNTIME_SCOPE_FILE" || true

PGHOST="${PGHOST:-$(runtime_scope_get_metadata PGHOST "localhost")}"
PGPORT="${PGPORT:-$(runtime_scope_get_metadata PGPORT "5444")}"
PGUSER="${PGUSER:-$(runtime_scope_get_metadata PGUSER "postgres")}"
PGPASSWORD="${PGPASSWORD:-$(runtime_scope_get_metadata PGPASSWORD "")}"
PGDATABASE="${PGDATABASE:-$(runtime_scope_get_metadata PGDATABASE "fmrif_scheduler")}"
APP_PORT="${APP_PORT:-$(runtime_scope_get_metadata APP_PORT "5051")}"
MAILPIT__PORT="${MAILPIT__PORT:-$(runtime_scope_get_metadata MAILPIT_APP_PORT "")}"
MAILPIT__SMTP_PORT="${MAILPIT__SMTP_PORT:-$(runtime_scope_get_metadata MAILPIT_APP_SMTP_PORT "")}"
MAIL__DEFAULT_SENDER="${MAIL__DEFAULT_SENDER:-$(runtime_scope_get_metadata MAIL__DEFAULT_SENDER "")}"

missing=()
for var in PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE MAIL__DEFAULT_SENDER; do
  if [[ -z "${!var:-}" ]]; then
    missing+=("$var")
  fi
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "ERROR: missing required variables in $env_file: ${missing[*]}" >&2
  exit 1
fi

if [[ "$MAIL__DEFAULT_SENDER" != *"@"* ]]; then
  echo "ERROR: MAIL__DEFAULT_SENDER must be a valid email address: $MAIL__DEFAULT_SENDER" >&2
  exit 1
fi

validate_port "$PGPORT" "PGPORT"
validate_port "$APP_PORT" "APP_PORT"
if [ -z "${MAILPIT__PORT}" ]; then
  MAILPIT__PORT=$((PGPORT + 1))
  if (( MAILPIT__PORT > 65535 )); then
    MAILPIT__PORT=8025
  fi
else
  validate_port "$MAILPIT__PORT" "MAILPIT__PORT"
fi
if [ -z "${MAILPIT__SMTP_PORT}" ]; then
  MAILPIT__SMTP_PORT=$((PGPORT + 2))
  if (( MAILPIT__SMTP_PORT > 65535 )); then
    MAILPIT__SMTP_PORT=8026
  fi
else
  validate_port "$MAILPIT__SMTP_PORT" "MAILPIT__SMTP_PORT"
fi

if [ "$MAILPIT__PORT" = "$APP_PORT" ] || [ "$MAILPIT__PORT" = "$PGPORT" ]; then
  echo "ERROR: MAILPIT__PORT must differ from APP_PORT ($APP_PORT) and PGPORT ($PGPORT)." >&2
  exit 1
fi
if [ "$MAILPIT__SMTP_PORT" = "$APP_PORT" ] || [ "$MAILPIT__SMTP_PORT" = "$PGPORT" ] || [ "$MAILPIT__SMTP_PORT" = "$MAILPIT__PORT" ]; then
  echo "ERROR: MAILPIT__SMTP_PORT must differ from APP_PORT ($APP_PORT), PGPORT ($PGPORT), and MAILPIT__PORT ($MAILPIT__PORT)." >&2
  exit 1
fi

scope_offset="${FMRIF_RUNTIME_SCOPE_OFFSET:-$(runtime_scope_get_metadata FMRIF_RUNTIME_SCOPE_OFFSET 0)}"
validate_non_negative_int "$scope_offset" "FMRIF_RUNTIME_SCOPE_OFFSET"

base_app_port="$APP_PORT"
base_pgport="$PGPORT"
base_mailpit_port="$MAILPIT__PORT"
base_mailpit_smtp_port="$MAILPIT__SMTP_PORT"
base_integration_app_port=$((base_app_port + 60))
base_mailpit_unit_port=$((base_mailpit_port + 20))
base_mailpit_unit_smtp_port=$((base_mailpit_smtp_port + 20))
base_mailpit_routes_port=$((base_mailpit_port + 40))
base_mailpit_routes_smtp_port=$((base_mailpit_smtp_port + 40))
base_mailpit_integration_port=$((base_mailpit_port + 60))
base_mailpit_integration_smtp_port=$((base_mailpit_smtp_port + 60))

APP_PORT=$((base_app_port + scope_offset))
PGPORT=$((base_pgport + scope_offset))
MAILPIT__PORT=$((base_mailpit_port + scope_offset))
MAILPIT__SMTP_PORT=$((base_mailpit_smtp_port + scope_offset))

SESSION__COOKIE_NAME="${SESSION__COOKIE_NAME:-$(runtime_scope_get_metadata SESSION__COOKIE_NAME "")}"
SESSION__COOKIE_NAME="${SESSION__COOKIE_NAME:-dsid-${RUNTIME_SCOPE}}"
SESSION__COOKIE_NAME="$(coalesce_session_cookie_name "$SESSION__COOKIE_NAME")"

export PORT="$APP_PORT"
export APP_PORT
export PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE
export MAILPIT__PORT MAILPIT__SMTP_PORT
export MAIL__SERVER="${MAIL__SERVER:-localhost}"
export MAIL__PORT="${MAILPIT__SMTP_PORT}"
export MAIL__SUPPRESS_SEND="${MAIL__SUPPRESS_SEND:-false}"
export SESSION__COOKIE_NAME
export FLASK_APP="${FLASK_APP:-scheduler.app:create_app}"

export RUNTIME_SCOPE_PGHOST="$PGHOST"
export RUNTIME_SCOPE_PGPORT="$base_pgport"
export RUNTIME_SCOPE_APP_PORT="$base_app_port"
export RUNTIME_SCOPE_INTEGRATION_APP_PORT="$base_integration_app_port"
export RUNTIME_SCOPE_MAILPIT_APP_PORT="$base_mailpit_port"
export RUNTIME_SCOPE_MAILPIT_APP_SMTP_PORT="$base_mailpit_smtp_port"
export RUNTIME_SCOPE_MAILPIT_UNIT_PORT="$base_mailpit_unit_port"
export RUNTIME_SCOPE_MAILPIT_UNIT_SMTP_PORT="$base_mailpit_unit_smtp_port"
export RUNTIME_SCOPE_MAILPIT_ROUTES_PORT="$base_mailpit_routes_port"
export RUNTIME_SCOPE_MAILPIT_ROUTES_SMTP_PORT="$base_mailpit_routes_smtp_port"
export RUNTIME_SCOPE_MAILPIT_INTEGRATION_PORT="$base_mailpit_integration_port"
export RUNTIME_SCOPE_MAILPIT_INTEGRATION_SMTP_PORT="$base_mailpit_integration_smtp_port"
export RUNTIME_SCOPE_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-${runtime_scope_get_metadata COMPOSE_PROJECT_NAME "scheduler"}}"
export RUNTIME_SCOPE_PGDATABASE="$PGDATABASE"
export RUNTIME_SCOPE_SCHEDULER_TEST_DB_NAME="${SCHEDULER_TEST_DB_NAME:-fmrif_scheduler_test}"
export RUNTIME_SCOPE_SESSION__COOKIE_NAME="$SESSION__COOKIE_NAME"
unset RUNTIME_SCOPE_HOST_APP_PID
export RUNTIME_SCOPE_AUTH_TEST__SHARED_SECRET="${AUTH_TEST__SHARED_SECRET:-}"
runtime_scope_write_metadata "$RUNTIME_SCOPE_FILE"

app_server="${APP_SERVER:-flask}"
declare -a server_command=()
case "$app_server" in
  flask)
    server_command=(flask run --host "${APP_BIND_HOST:-127.0.0.1}" --port "$APP_PORT")
    ;;
  gunicorn)
    mapfile -t gunicorn_command < <(build_gunicorn_command)
    server_command=("${gunicorn_command[@]}")
    ;;
  *)
    echo "ERROR: APP_SERVER must be one of: flask, gunicorn" >&2
    exit 1
    ;;
esac

SERVER_PID=""
trap 'forward_signal TERM' TERM
trap 'forward_signal INT' INT
trap 'cleanup_scope_metadata' EXIT

"${server_command[@]}" &
SERVER_PID=$!
export RUNTIME_SCOPE_HOST_APP_PID="$SERVER_PID"
runtime_scope_write_metadata "$RUNTIME_SCOPE_FILE"

readiness_url="http://127.0.0.1:${APP_PORT}/robots.txt"
if ! wait_for_local_http_ready "$readiness_url"; then
  stop_server
  exit 1
fi

if ! run_edge_header_gate; then
  stop_server
  exit 1
fi

wait "$SERVER_PID"
