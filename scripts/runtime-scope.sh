#!/usr/bin/env bash
set -euo pipefail

RUNTIME_SCOPE_DIR="${RUNTIME_SCOPE_DIR:-/tmp/fmrif-scheduler-runtimes}"
RUNTIME_SCOPE=""
RUNTIME_SCOPE_OFFSET=""
RUNTIME_SCOPE_FILE=""
RUNTIME_SCOPE_SOURCE="runtime-default"

runtime_scope_trim() {
  local value=$1
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

runtime_scope_unquote() {
  local value=$1
  if [ ${#value} -ge 2 ] && [ "${value:0:1}" = "${value: -1}" ] && {
    [ "${value:0:1}" = '"' ] || [ "${value:0:1}" = "'" ]
  }; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

runtime_scope_sanitize() {
  local raw=$1
  local value
  value="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"
  value="${value#-}"
  value="${value%-}"
  printf '%s' "${value:-default}"
}

runtime_scope_hash_offset() {
  local raw=$1
  local hash
  if [ "$raw" = "default" ]; then
    printf '0'
    return 0
  fi
  hash="$(printf '%s' "$raw" | cksum | awk '{print $1}')"
  printf '%s' $((hash % 2000))
}

runtime_scope_file_path() {
  local scope=$1
  printf '%s' "${RUNTIME_SCOPE_DIR}/${scope}"
}

runtime_scope_set_file() {
  local scope=$1
  RUNTIME_SCOPE_FILE="$(runtime_scope_file_path "$scope")"
}

runtime_scope_derive() {
  local raw_scope
  local sanitized

  raw_scope="${FMRIF_RUNTIME_SCOPE:-default}"
  sanitized="$(runtime_scope_sanitize "$raw_scope")"
  RUNTIME_SCOPE="$sanitized"
  RUNTIME_SCOPE_OFFSET="$(runtime_scope_hash_offset "$RUNTIME_SCOPE")"

  export FMRIF_RUNTIME_SCOPE="$RUNTIME_SCOPE"
  export FMRIF_RUNTIME_SCOPE_OFFSET="$RUNTIME_SCOPE_OFFSET"
  export RUNTIME_SCOPE RUNTIME_SCOPE_OFFSET
  runtime_scope_set_file "$RUNTIME_SCOPE"
  RUNTIME_SCOPE_SOURCE="runtime-derived"
}

runtime_scope_touch_file() {
  mkdir -p "$RUNTIME_SCOPE_DIR"
  : >"$RUNTIME_SCOPE_FILE"
}

runtime_scope_is_placeholder_value() {
  local value=$1
  [[ "$value" == __*__ ]]
}

runtime_scope_parse_kv_line() {
  local line=$1
  if [ -z "$line" ] || [ "${line:0:1}" = "#" ]; then
    return 1
  fi
  if [[ "$line" != *=* ]]; then
    return 1
  fi

  line="$(runtime_scope_trim "$line")"
  local key=${line%%=*}
  local value=${line#*=}
  key="$(runtime_scope_trim "$key")"
  value="$(runtime_scope_trim "$value")"
  value="$(runtime_scope_unquote "$value")"

  if [ -z "$key" ] || ! [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    return 1
  fi

  printf '%s=%s' "$key" "$value"
  return 0
}

runtime_scope_parse_kv_file_with_prefix() {
  local file=$1
  local prefix=${2:-}
  local line key value pair

  if [ ! -f "$file" ]; then
    return 1
  fi

  while IFS= read -r line || [ -n "$line" ]; do
    pair="$(runtime_scope_parse_kv_line "$line")"
    if [ -z "$pair" ]; then
      continue
    fi
    key="${pair%%=*}"
    value="${pair#*=}"
    printf -v "${prefix}${key}" '%s' "$value"
  done < "$file"
  return 0
}

runtime_scope_load_metadata() {
  local file=${1:-${RUNTIME_SCOPE_FILE:-}}
  if [ -z "$file" ]; then
    echo "ERROR: runtime metadata file path is empty." >&2
    return 1
  fi
  if [ ! -f "$file" ]; then
    return 1
  fi

  runtime_scope_clear_metadata_vars
  if ! runtime_scope_parse_kv_file_with_prefix "$file" "RUNTIME_SCOPE_"; then
    return 1
  fi

  RUNTIME_SCOPE_SOURCE="runtime-scope-file"
  return 0
}

runtime_scope_get_metadata() {
  local key=$1
  local default=${2:-}
  local meta_var="RUNTIME_SCOPE_${key}"
  printf '%s' "${!meta_var:-$default}"
}

runtime_scope_normalize_name() {
  local raw_name=$1
  local sanitized

  if [ -z "$raw_name" ]; then
    raw_name="scheduler"
  fi

  sanitized="$(printf '%s' "$raw_name" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_' '-')"
  sanitized="${sanitized#-}"
  sanitized="${sanitized%-}"
  printf '%s' "${sanitized:-scheduler}"
}

runtime_scope_current_worktree() {
  local root=""
  if command -v git >/dev/null 2>&1; then
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  fi
  printf '%s' "${root}"
}

runtime_scope_set_compose_project_name() {
  local base_name=${1:-scheduler}
  local derived=$base_name

  if [ -z "$derived" ]; then
    derived="scheduler"
  fi

  if [ "${RUNTIME_SCOPE:-default}" != "default" ]; then
    case "$derived" in
      *-"${RUNTIME_SCOPE}")
        ;;
      *)
        derived="${derived}-${RUNTIME_SCOPE}"
        ;;
    esac
  fi

  COMPOSE_PROJECT_NAME="$(runtime_scope_normalize_name "$derived")"
  export COMPOSE_PROJECT_NAME
}

runtime_scope_clear_metadata_vars() {
  for var in \
    RUNTIME_SCOPE_RUNTIME_SCOPE \
    RUNTIME_SCOPE_FMRIF_RUNTIME_SCOPE_OFFSET \
    RUNTIME_SCOPE_PGHOST \
    RUNTIME_SCOPE_PGPORT \
    RUNTIME_SCOPE_WORKTREE_ROOT \
    RUNTIME_SCOPE_PGUSER \
    RUNTIME_SCOPE_PGPASSWORD \
    RUNTIME_SCOPE_APP_PORT \
    RUNTIME_SCOPE_INTEGRATION_APP_PORT \
    RUNTIME_SCOPE_MAILPIT_APP_PORT \
    RUNTIME_SCOPE_MAILPIT_APP_SMTP_PORT \
    RUNTIME_SCOPE_MAILPIT_UNIT_PORT \
    RUNTIME_SCOPE_MAILPIT_UNIT_SMTP_PORT \
    RUNTIME_SCOPE_MAILPIT_ROUTES_PORT \
    RUNTIME_SCOPE_MAILPIT_ROUTES_SMTP_PORT \
    RUNTIME_SCOPE_MAILPIT_INTEGRATION_PORT \
    RUNTIME_SCOPE_MAILPIT_INTEGRATION_SMTP_PORT \
    RUNTIME_SCOPE_COMPOSE_PROJECT_NAME \
    RUNTIME_SCOPE_PGDATABASE \
    RUNTIME_SCOPE_SCHEDULER_TEST_DB_NAME \
    RUNTIME_SCOPE_SESSION__COOKIE_NAME \
    RUNTIME_SCOPE_HOST_APP_PID \
    RUNTIME_SCOPE_AUTH_TEST__SHARED_SECRET \
    RUNTIME_SCOPE_MAIL__DEFAULT_SENDER; do
    unset "$var" 2>/dev/null || true
  done
}

runtime_scope_write_metadata() {
  local file=${1:-${RUNTIME_SCOPE_FILE:-}}
  if [ -z "$file" ]; then
    echo "ERROR: runtime metadata file path is empty." >&2
    return 1
  fi

  mkdir -p "$RUNTIME_SCOPE_DIR"

  local scope_pg_host="${RUNTIME_SCOPE_PGHOST:-${PGHOST:-}}"
  local scope_pg_port="${RUNTIME_SCOPE_PGPORT:-${PGPORT:-}}"
  local scope_app_port="${RUNTIME_SCOPE_APP_PORT:-${APP_PORT:-}}"
  local scope_integration_app_port="${RUNTIME_SCOPE_INTEGRATION_APP_PORT:-${INTEGRATION_APP_PORT:-}}"
  local scope_mailpit_app_port="${RUNTIME_SCOPE_MAILPIT_APP_PORT:-${MAILPIT__PORT:-}}"
  local scope_mailpit_app_smtp_port="${RUNTIME_SCOPE_MAILPIT_APP_SMTP_PORT:-${MAILPIT__SMTP_PORT:-}}"
  local scope_mailpit_unit_port="${RUNTIME_SCOPE_MAILPIT_UNIT_PORT:-${MAILPIT_UNIT__PORT:-}}"
  local scope_mailpit_unit_smtp_port="${RUNTIME_SCOPE_MAILPIT_UNIT_SMTP_PORT:-${MAILPIT_UNIT__SMTP_PORT:-}}"
  local scope_mailpit_routes_port="${RUNTIME_SCOPE_MAILPIT_ROUTES_PORT:-${MAILPIT_ROUTES__PORT:-}}"
  local scope_mailpit_routes_smtp_port="${RUNTIME_SCOPE_MAILPIT_ROUTES_SMTP_PORT:-${MAILPIT_ROUTES__SMTP_PORT:-}}"
  local scope_mailpit_integration_port="${RUNTIME_SCOPE_MAILPIT_INTEGRATION_PORT:-${MAILPIT_INTEGRATION__PORT:-}}"
  local scope_mailpit_integration_smtp_port="${RUNTIME_SCOPE_MAILPIT_INTEGRATION_SMTP_PORT:-${MAILPIT_INTEGRATION__SMTP_PORT:-}}"
  local scope_compose_project="${RUNTIME_SCOPE_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-}}"
  local scope_pg_database="${RUNTIME_SCOPE_PGDATABASE:-${PGDATABASE:-}}"
  local scope_scheduler_test_db="${RUNTIME_SCOPE_SCHEDULER_TEST_DB_NAME:-${SCHEDULER_TEST_DB_NAME:-}}"
  local scope_session_cookie="${RUNTIME_SCOPE_SESSION__COOKIE_NAME:-${SESSION__COOKIE_NAME:-}}"
  local scope_host_app_pid="${RUNTIME_SCOPE_HOST_APP_PID:-}"
  local scope_auth_secret="${RUNTIME_SCOPE_AUTH_TEST__SHARED_SECRET:-${AUTH_TEST__SHARED_SECRET:-}}"
  local scope_worktree_root="${RUNTIME_SCOPE_WORKTREE_ROOT:-$(runtime_scope_current_worktree)}"

  cat > "$file" <<EOF
RUNTIME_SCOPE=${RUNTIME_SCOPE}
FMRIF_RUNTIME_SCOPE_OFFSET=${FMRIF_RUNTIME_SCOPE_OFFSET}
COMPOSE_PROJECT_NAME=${scope_compose_project}
PGHOST=${scope_pg_host}
PGPORT=${scope_pg_port}
APP_PORT=${scope_app_port}
INTEGRATION_APP_PORT=${scope_integration_app_port}
MAILPIT_APP_PORT=${scope_mailpit_app_port}
MAILPIT_APP_SMTP_PORT=${scope_mailpit_app_smtp_port}
MAILPIT_UNIT_PORT=${scope_mailpit_unit_port}
MAILPIT_UNIT_SMTP_PORT=${scope_mailpit_unit_smtp_port}
MAILPIT_ROUTES_PORT=${scope_mailpit_routes_port}
MAILPIT_ROUTES_SMTP_PORT=${scope_mailpit_routes_smtp_port}
MAILPIT_INTEGRATION_PORT=${scope_mailpit_integration_port}
MAILPIT_INTEGRATION_SMTP_PORT=${scope_mailpit_integration_smtp_port}
PGDATABASE=${scope_pg_database}
SCHEDULER_TEST_DB_NAME=${scope_scheduler_test_db}
SESSION__COOKIE_NAME=${scope_session_cookie}
HOST_APP_PID=${scope_host_app_pid}
AUTH_TEST__SHARED_SECRET=${scope_auth_secret}
WORKTREE_ROOT=${scope_worktree_root}
EOF
}
