#!/usr/bin/env bash
set -euo pipefail

: "${ENVFILE:=.env}"

declare -a LOADED_ENV_KEYS=()
COMPOSE_ENV_FILE=""
RUNTIME_ENV_FILE=""

cleanup_compose_env_file() {
  if [ -n "${COMPOSE_ENV_FILE}" ] && [ -f "$COMPOSE_ENV_FILE" ]; then
    rm -f "$COMPOSE_ENV_FILE"
  fi
  if [ -n "${RUNTIME_ENV_FILE}" ] && [ -f "$RUNTIME_ENV_FILE" ]; then
    rm -f "$RUNTIME_ENV_FILE"
  fi
}

trap cleanup_compose_env_file EXIT

compose_name_for_compose() {
  local raw_name=$1
  local sanitized

  if [ -z "$raw_name" ]; then
    raw_name="$(basename "$PWD")"
  fi

  sanitized="$(printf '%s' "$raw_name" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_' '-')"
  sanitized="${sanitized#-}"
  sanitized="${sanitized%-}"
  printf '%s' "${sanitized:-scheduler}"
}

resolve_compose_project() {
  local override="${COMPOSE_PROJECT_NAME:-${SCHEDULER_COMPOSE_PROJECT_NAME:-}}"
  local derived="$override"

  if [ -z "$derived" ]; then
    # Keep default compose resources isolated by local app listener.
    derived="$(basename "$PWD")-${APP_PORT:-5051}"
  fi

  COMPOSE_PROJECT_NAME="$(compose_name_for_compose "$derived")"
  export COMPOSE_PROJECT_NAME
}

show_help() {
  cat <<'EOF'
Usage:
  ./run-compose.sh             # validate env and start compose
  ./run-compose.sh --check     # validate env + compose before startup
  ./run-compose.sh --help      # show this help
Optional:
  Set COMPOSE_PROJECT_NAME for parallel stacks
EOF
}

trim() {
  local value=$1
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

load_env_file() {
  local file=$1
  local line key value

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="$(trim "$line")"
    if [[ -z "$line" || "${line:0:1}" == "#" ]]; then
      continue
    fi

    if [[ "$line" != *"="* ]]; then
      echo "ERROR: invalid line in $file: $line" >&2
      return 1
    fi

    key="${line%%=*}"
    value="${line#*=}"
    key="$(trim "$key")"
    value="$(trim "$value")"

    if [[ -z "$key" ]]; then
      echo "ERROR: missing key in $file: $line" >&2
      return 1
    fi

    # Respect already-exported values so callers can override .env per run.
    if [[ -n "${!key+_}" ]]; then
      LOADED_ENV_KEYS+=("$key")
      continue
    fi

    # Preserve value as-is; only strip matching outer quotes.
    if [ "${#value}" -ge 2 ] && [ "${value:0:1}" = "${value: -1}" ] \
      && { [ "${value:0:1}" = "\"" ] || [ "${value:0:1}" = "'" ]; }; then
      value="${value:1:${#value}-2}"
    fi

    printf -v "$key" '%s' "$value"
    export "$key"
    LOADED_ENV_KEYS+=("$key")
  done < "$file"
}

build_compose_env_file() {
  local out_file=$1
  local -a keys=(
    "APP_PORT"
    "PGPORT"
    "PGUSER"
    "PGPASSWORD"
    "PGDATABASE"
  )

  : > "$out_file"

  local key value
  for key in "${keys[@]}"; do
    if [ -z "${!key+_}" ]; then
      continue
    fi

    value="${!key}"
    value="${value//\$/\$\$}"
    printf '%s=%s\n' "$key" "$value" >> "$out_file"
  done
}

build_runtime_env_file() {
  local out_file=$1
  local -a keys=(
    "${LOADED_ENV_KEYS[@]}"
    "APP_PORT"
    "PGHOST"
    "PGPORT"
    "PGUSER"
    "PGPASSWORD"
    "PGDATABASE"
    "SERVER__SERVER_NAME"
  )
  declare -A emitted=()

  : > "$out_file"

  local key value
  for key in "${keys[@]}"; do
    if [[ -n "${emitted[$key]:-}" ]]; then
      continue
    fi
    emitted["$key"]=1

    if [ -z "${!key+_}" ]; then
      continue
    fi

    value="${!key}"
    printf '%s=%s\n' "$key" "$value" >> "$out_file"
  done
}

prepare_compose_config() {
  COMPOSE_ENV_FILE="$(mktemp /tmp/scheduler-compose-env.XXXXXX)"
  build_compose_env_file "$COMPOSE_ENV_FILE"
  # Keep interpolation and env_file inputs aligned to the escaped compose env.
  export SCHEDULER_COMPOSE_ENV_FILE="$COMPOSE_ENV_FILE"

  RUNTIME_ENV_FILE="$(mktemp /tmp/scheduler-runtime-env.XXXXXX)"
  build_runtime_env_file "$RUNTIME_ENV_FILE"
  export SCHEDULER_RUNTIME_ENV_FILE="$RUNTIME_ENV_FILE"
}

validate_runtime_env() {
  if [ ! -f "$ENVFILE" ]; then
    echo "ERROR: $ENVFILE was not found. Run ./setup-dotenv.sh first." >&2
    return 1
  fi

  # Keep parser tolerant of values that would break `source`.
  load_env_file "$ENVFILE"

  local missing_env=()
  for var in PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE; do
    if [[ -z "${!var:-}" ]]; then
      missing_env+=("$var")
    fi
  done
  if [ ${#missing_env[@]} -gt 0 ]; then
    echo "ERROR: missing required variables in $ENVFILE: ${missing_env[*]}" >&2
    return 1
  fi

  if [[ ! "$PGPORT" =~ ^[0-9]+$ ]] || (( PGPORT < 1 || PGPORT > 65535 )); then
    echo "ERROR: PGPORT must be between 1 and 65535: $PGPORT" >&2
    return 1
  fi

  : "${APP_PORT:=5051}"
  if [[ ! "$APP_PORT" =~ ^[0-9]+$ ]] || (( APP_PORT < 1 || APP_PORT > 65535 )); then
    echo "ERROR: APP_PORT must be between 1 and 65535: $APP_PORT" >&2
    return 1
  fi

  export PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE APP_PORT

  return 0
}

warn_local_port_overrides() {
  local app_port=$1
  local warning_lines=()

  local server_name="${SERVER__SERVER_NAME:-}"
  if [[ "$server_name" =~ ^(localhost|localhost\.localdomain|127\.0\.0\.1):([0-9]{1,5})$ ]]; then
    local server_name_port="${BASH_REMATCH[2]}"
    if [ "$server_name_port" != "$app_port" ]; then
      warning_lines+=(
        "SERVER__SERVER_NAME=$server_name does not match APP_PORT=$app_port."
        "  Local compose derives SERVER__SERVER_NAME from APP_PORT; remove this override or set localhost:$app_port."
      )
    fi
  fi

  local playwright_base_url="${PLAYWRIGHT_BASE_URL:-${BASE_URL:-}}"
  if [[ "$playwright_base_url" =~ ^https?://(localhost|localhost\.localdomain|127\.0\.0\.1):([0-9]{1,5})(/.*)?$ ]]; then
    local playwright_port="${BASH_REMATCH[2]}"
    if [ "$playwright_port" != "$app_port" ]; then
      warning_lines+=(
        "PLAYWRIGHT_BASE_URL=$playwright_base_url does not match APP_PORT=$app_port."
        "  Local Playwright port is auto-synced from APP_PORT; update or unset this override to reduce confusion."
      )
    fi
  fi

  if [ ${#warning_lines[@]} -gt 0 ]; then
    echo "WARN: local port overrides are inconsistent:" >&2
    local line
    for line in "${warning_lines[@]}"; do
      echo "  - $line" >&2
    done
  fi
}

run_preflight() {
  validate_runtime_env || return 1
  resolve_compose_project
  prepare_compose_config

  # Keep container variables aligned even if only PG* values are set.
  : "${APP_PORT:=5051}"
  export APP_PORT PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE
  warn_local_port_overrides "$APP_PORT"

  if [ ! -f "compose.yaml" ]; then
    echo "ERROR: compose.yaml not found" >&2
    return 1
  fi

  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is required for compose startup." >&2
    return 1
  fi
  if ! docker compose --project-name "$COMPOSE_PROJECT_NAME" --env-file "$COMPOSE_ENV_FILE" config >/dev/null 2>&1; then
    echo "ERROR: docker compose config failed. Run `docker compose config` for details." >&2
    return 1
  fi

  local resolved_seed_dir="."
  if [ -n "${SQL_SEED_DUMP_FILE:-}" ] || [ -n "${SQL_USER_DEPT_CSV:-}" ] || [ -n "${SQL_DEV_DEPT_CSV:-}" ] || [ -n "${SQL_DEVPERM_CSV:-}" ]; then
    for seed_file in \
      "${SQL_SEED_DUMP_FILE:-}" \
      "${SQL_USER_DEPT_CSV:-}" \
      "${SQL_DEV_DEPT_CSV:-}" \
      "${SQL_DEVPERM_CSV:-}"
    do
      if [ -n "${seed_file:-}" ] && [ ! -f "$seed_file" ]; then
        echo "ERROR: missing override seed file: $seed_file" >&2
        return 1
      fi
    done
  else
    resolved_seed_dir="sql"
    for seed_file in \
      "$resolved_seed_dir/001-schema.sql" \
      "$resolved_seed_dir/003-import-data.sql" \
      "$resolved_seed_dir/user-dept.csv" \
      "$resolved_seed_dir/dev-dept.csv" \
      "$resolved_seed_dir/devperm.csv"
    do
      if [ ! -f "$seed_file" ]; then
        echo "ERROR: missing seed file: $seed_file" >&2
        return 1
      fi
    done
  fi

  echo "Preflight checks passed."
  echo "  App port: $APP_PORT"
  echo "  DB (app-facing): $PGHOST:$PGPORT/$PGDATABASE"
  echo "  Compose project: $COMPOSE_PROJECT_NAME"
  echo "  DB (container): postgres wrapper exports POSTGRES_* from PG*"
  return 0
}

case "${1:-}" in
  --help|-h)
    show_help
    exit 0
    ;;
  --check)
    run_preflight
    exit $?
    ;;
  "")
    validate_runtime_env || exit 1
    ;;
  *)
    echo "ERROR: unknown argument: ${1:-}" >&2
    show_help
    exit 1
    ;;
esac

: "${APP_PORT:=5051}"
export APP_PORT PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE

resolve_compose_project

echo "Using environment from $ENVFILE"
echo "  App port: $APP_PORT"
echo "  DB (app-facing): $PGHOST:$PGPORT/$PGDATABASE"
echo "  Compose project: $COMPOSE_PROJECT_NAME"
echo "  DB bootstrap aliases: PGUSER/PGPASSWORD/PGDATABASE in containerized postgres"

prepare_compose_config
docker compose --project-name "$COMPOSE_PROJECT_NAME" --env-file "$COMPOSE_ENV_FILE" up --build
