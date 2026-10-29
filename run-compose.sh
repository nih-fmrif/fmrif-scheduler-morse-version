#!/usr/bin/env bash
set -euo pipefail

: "${ENVFILE:=.env}"
RUNTIME_SCOPE_DIR="/tmp/fmrif-scheduler-runtimes"

declare -a LOADED_ENV_KEYS=()
COMPOSE_ENV_FILE=""
RUNTIME_ENV_FILE=""
RUNTIME_SCOPE=""
RUNTIME_SCOPE_OFFSET=0
RUNTIME_SCOPE_FILE=""

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

sanitize_scope() {
  local raw=$1
  local value
  value="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"
  value="${value#-}"
  value="${value%-}"
  printf '%s' "${value:-default}"
}

scope_hash_offset() {
  local raw=$1
  local hash
  if [ "$raw" = "default" ]; then
    printf '0'
    return 0
  fi
  hash="$(printf '%s' "$raw" | cksum | awk '{print $1}')"
  printf '%s' $((hash % 2000))
}

derive_runtime_scope() {
  local raw_scope
  raw_scope="${FMRIF_RUNTIME_SCOPE:-default}"
  RUNTIME_SCOPE="$(sanitize_scope "$raw_scope")"
  RUNTIME_SCOPE_OFFSET="$(scope_hash_offset "$RUNTIME_SCOPE")"
  export FMRIF_RUNTIME_SCOPE="$RUNTIME_SCOPE"
  export FMRIF_RUNTIME_SCOPE_OFFSET="$RUNTIME_SCOPE_OFFSET"
}

acquire_runtime_scope_file() {
  mkdir -p "$RUNTIME_SCOPE_DIR"
  RUNTIME_SCOPE_FILE="${RUNTIME_SCOPE_DIR}/${RUNTIME_SCOPE}"
  : >"$RUNTIME_SCOPE_FILE"
  return 0
}

resolve_compose_project() {
  local base_name="${SCHEDULER_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-}}"
  local derived="$base_name"

  if [ -z "$derived" ]; then
    derived="$(basename "$PWD")"
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

  COMPOSE_PROJECT_NAME="$(compose_name_for_compose "$derived")"
  export COMPOSE_PROJECT_NAME
}

compose_project_has_running_services() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  docker ps \
    --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
    --filter "status=running" \
    -q | grep -q .
}

show_scope_running_guidance() {
  if [ "$RUNTIME_SCOPE" = "default" ]; then
    echo "Default stack is already running."
    echo "(Agents: set \`FMRIF_RUNTIME_SCOPE=<unique-scope>\` and rerun.)"
    echo "Run \`bash run-compose.sh --reset\` to replace it."
    return 0
  fi

  echo "Stack for scope '${RUNTIME_SCOPE}' is already running."
  echo "Run \`FMRIF_RUNTIME_SCOPE=${RUNTIME_SCOPE} bash run-compose.sh --reset\` to replace it."
  echo "Or choose a different \`FMRIF_RUNTIME_SCOPE\`."
}

START_NO_APP=0
RESUME_STACK=0
CHECK_ONLY=0
RESET_STACK=0

show_help() {
  cat <<'EOF'
Usage:
  ./run-compose.sh --no-app            # recommended local dev: postgres + mailpit services only
  ./run-compose.sh --no-app --resume   # reuse existing postgres/mailpit data
  ./run-compose.sh --no-app --reset    # replace stack and wipe volumes
  ./run-compose.sh                     # full compose stack (includes app container)
  ./run-compose.sh --resume            # resume existing full stack without destructive reset
  ./run-compose.sh --reset             # replace full stack and wipe volumes
  ./run-compose.sh --check     # validate env + compose before startup
  ./run-compose.sh --help      # show this help
Optional:
  Set COMPOSE_PROJECT_NAME for parallel stacks
Note: direct `docker compose` is not supported for this workflow.
EOF
}

trim() {
  local value=$1
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

validate_port() {
  local port=$1
  local name=$2
  if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    echo "ERROR: ${name} must be between 1 and 65535: ${port}" >&2
    return 1
  fi
}

ensure_ports_distinct() {
  local -a ports=("$@")
  local i j
  for ((i = 0; i < ${#ports[@]}; i += 1)); do
    for ((j = i + 1; j < ${#ports[@]}; j += 1)); do
      if [ "${ports[$i]}" = "${ports[$j]}" ]; then
        echo "ERROR: scoped runtime ports collided (${ports[$i]}). Set a different FMRIF_RUNTIME_SCOPE." >&2
        return 1
      fi
    done
  done
}

port_is_in_use() {
  local port=$1

  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1
    return
  fi

  if command -v ss >/dev/null 2>&1; then
    ss -H -ltn "sport = :$port" 2>/dev/null | grep -q .
    return
  fi

  if command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | awk -v port="$port" '
      /LISTEN/ && $0 ~ ("[\\.:]" port "([[:space:]]|$)") { found=1; exit }
      END { exit(found ? 0 : 1) }
    '
    return
  fi

  local python_cmd=""
  if command -v python3 >/dev/null 2>&1; then
    python_cmd="python3"
  elif command -v python >/dev/null 2>&1; then
    python_cmd="python"
  fi

  if [ -z "$python_cmd" ]; then
    return 1
  fi

  "$python_cmd" - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
hosts = [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")]
in_use = False

for family, host in hosts:
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        continue
    try:
        if family == socket.AF_INET6:
            try:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            except OSError:
                pass
        sock.bind((host, port))
    except OSError:
        in_use = True
        break
    finally:
        sock.close()

raise SystemExit(0 if in_use else 1)
PY
}

ensure_scoped_ports_free() {
  local conflicts=()
  local pair key port
  for pair in "$@"; do
    key="${pair%%:*}"
    port="${pair#*:}"
    if port_is_in_use "$port"; then
      conflicts+=("${key}=${port}")
    fi
  done
  if [ "${#conflicts[@]}" -gt 0 ]; then
    echo "ERROR: scoped runtime ports already in use: ${conflicts[*]}" >&2
    echo "ERROR: choose a different FMRIF_RUNTIME_SCOPE." >&2
    return 1
  fi
  return 0
}

ensure_all_scoped_ports_free() {
  ensure_scoped_ports_free \
    "PGPORT:${PGPORT}" \
    "APP_PORT:${APP_PORT}" \
    "INTEGRATION_APP_PORT:${INTEGRATION_APP_PORT}" \
    "MAILPIT__PORT:${MAILPIT__PORT}" \
    "MAILPIT__SMTP_PORT:${MAILPIT__SMTP_PORT}" \
    "MAILPIT_UNIT__PORT:${MAILPIT_UNIT__PORT}" \
    "MAILPIT_UNIT__SMTP_PORT:${MAILPIT_UNIT__SMTP_PORT}" \
    "MAILPIT_ROUTES__PORT:${MAILPIT_ROUTES__PORT}" \
    "MAILPIT_ROUTES__SMTP_PORT:${MAILPIT_ROUTES__SMTP_PORT}" \
    "MAILPIT_INTEGRATION__PORT:${MAILPIT_INTEGRATION__PORT}" \
    "MAILPIT_INTEGRATION__SMTP_PORT:${MAILPIT_INTEGRATION__SMTP_PORT}"
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
    LOADED_ENV_KEYS+=("$key")
  done < "$file"
}

build_compose_env_file() {
  local out_file=$1
  local -a keys=(
    "FMRIF_COMPOSE_WRAPPER"
    "APP_PORT"
    "PGPORT"
    "MAILPIT__PORT"
    "MAILPIT__SMTP_PORT"
    "MAILPIT_UNIT__PORT"
    "MAILPIT_UNIT__SMTP_PORT"
    "MAILPIT_ROUTES__PORT"
    "MAILPIT_ROUTES__SMTP_PORT"
    "MAILPIT_INTEGRATION__PORT"
    "MAILPIT_INTEGRATION__SMTP_PORT"
    "PGUSER"
    "PGPASSWORD"
    "PGDATABASE"
    "SERVER__SERVER_NAME"
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
    "MAILPIT__PORT"
    "MAILPIT__SMTP_PORT"
    "MAILPIT_UNIT__PORT"
    "MAILPIT_UNIT__SMTP_PORT"
    "MAILPIT_ROUTES__PORT"
    "MAILPIT_ROUTES__SMTP_PORT"
    "MAILPIT_INTEGRATION__PORT"
    "MAILPIT_INTEGRATION__SMTP_PORT"
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
  for var in PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE MAIL__DEFAULT_SENDER; do
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

  if [[ "$MAIL__DEFAULT_SENDER" != *"@"* ]]; then
    echo "ERROR: MAIL__DEFAULT_SENDER must be a valid email address: $MAIL__DEFAULT_SENDER" >&2
    return 1
  fi

  : "${APP_PORT:=5051}"
  if [[ ! "$APP_PORT" =~ ^[0-9]+$ ]] || (( APP_PORT < 1 || APP_PORT > 65535 )); then
    echo "ERROR: APP_PORT must be between 1 and 65535: $APP_PORT" >&2
    return 1
  fi

  if [[ -n "${MAILPIT__PORT:-}" ]]; then
    if [[ ! "$MAILPIT__PORT" =~ ^[0-9]+$ ]] || (( MAILPIT__PORT < 1 || MAILPIT__PORT > 65535 )); then
      echo "ERROR: MAILPIT__PORT must be between 1 and 65535: $MAILPIT__PORT" >&2
      return 1
    fi
  else
    MAILPIT__PORT=$((PGPORT + 1))
    if (( MAILPIT__PORT > 65535 )); then
      MAILPIT__PORT=8025
    fi
  fi

  if [ "$MAILPIT__PORT" = "$APP_PORT" ] || [ "$MAILPIT__PORT" = "$PGPORT" ]; then
    echo "ERROR: MAILPIT__PORT must differ from APP_PORT ($APP_PORT) and PGPORT ($PGPORT)." >&2
    return 1
  fi

  if [[ -n "${MAILPIT__SMTP_PORT:-}" ]]; then
    if [[ ! "$MAILPIT__SMTP_PORT" =~ ^[0-9]+$ ]] || (( MAILPIT__SMTP_PORT < 1 || MAILPIT__SMTP_PORT > 65535 )); then
      echo "ERROR: MAILPIT__SMTP_PORT must be between 1 and 65535: $MAILPIT__SMTP_PORT" >&2
      return 1
    fi
  else
    MAILPIT__SMTP_PORT=$((PGPORT + 2))
    if (( MAILPIT__SMTP_PORT > 65535 )); then
      MAILPIT__SMTP_PORT=8026
    fi
  fi

  if [ "$MAILPIT__SMTP_PORT" = "$APP_PORT" ] || [ "$MAILPIT__SMTP_PORT" = "$PGPORT" ] || [ "$MAILPIT__SMTP_PORT" = "$MAILPIT__PORT" ]; then
    echo "ERROR: MAILPIT__SMTP_PORT must differ from APP_PORT ($APP_PORT), PGPORT ($PGPORT), and MAILPIT__PORT ($MAILPIT__PORT)." >&2
    return 1
  fi

  local scope_offset="${FMRIF_RUNTIME_SCOPE_OFFSET:-0}"
  local scoped_pgport scoped_app_port
  local integration_app_port
  local mailpit_app_port mailpit_app_smtp_port
  local mailpit_unit_port mailpit_unit_smtp_port
  local mailpit_routes_port mailpit_routes_smtp_port
  local mailpit_integration_port mailpit_integration_smtp_port

  scoped_pgport=$((PGPORT + scope_offset))
  scoped_app_port=$((APP_PORT + scope_offset))
  integration_app_port=$((scoped_app_port + 60))
  mailpit_app_port=$((MAILPIT__PORT + scope_offset))
  mailpit_app_smtp_port=$((MAILPIT__SMTP_PORT + scope_offset))

  mailpit_unit_port=$((mailpit_app_port + 20))
  mailpit_unit_smtp_port=$((mailpit_app_smtp_port + 20))
  mailpit_routes_port=$((mailpit_app_port + 40))
  mailpit_routes_smtp_port=$((mailpit_app_smtp_port + 40))
  mailpit_integration_port=$((mailpit_app_port + 60))
  mailpit_integration_smtp_port=$((mailpit_app_smtp_port + 60))

  validate_port "$scoped_pgport" "PGPORT (scoped)" || return 1
  validate_port "$scoped_app_port" "APP_PORT (scoped)" || return 1
  validate_port "$integration_app_port" "INTEGRATION_APP_PORT (scoped)" || return 1
  validate_port "$mailpit_app_port" "MAILPIT__PORT (app scoped)" || return 1
  validate_port "$mailpit_app_smtp_port" "MAILPIT__SMTP_PORT (app scoped)" || return 1
  validate_port "$mailpit_unit_port" "MAILPIT_UNIT__PORT" || return 1
  validate_port "$mailpit_unit_smtp_port" "MAILPIT_UNIT__SMTP_PORT" || return 1
  validate_port "$mailpit_routes_port" "MAILPIT_ROUTES__PORT" || return 1
  validate_port "$mailpit_routes_smtp_port" "MAILPIT_ROUTES__SMTP_PORT" || return 1
  validate_port "$mailpit_integration_port" "MAILPIT_INTEGRATION__PORT" || return 1
  validate_port "$mailpit_integration_smtp_port" "MAILPIT_INTEGRATION__SMTP_PORT" || return 1

  ensure_ports_distinct \
    "$scoped_pgport" \
    "$scoped_app_port" \
    "$integration_app_port" \
    "$mailpit_app_port" \
    "$mailpit_app_smtp_port" \
    "$mailpit_unit_port" \
    "$mailpit_unit_smtp_port" \
    "$mailpit_routes_port" \
    "$mailpit_routes_smtp_port" \
    "$mailpit_integration_port" \
    "$mailpit_integration_smtp_port" || return 1

  PGPORT="$scoped_pgport"
  APP_PORT="$scoped_app_port"
  INTEGRATION_APP_PORT="$integration_app_port"
  MAILPIT__PORT="$mailpit_app_port"
  MAILPIT__SMTP_PORT="$mailpit_app_smtp_port"
  MAILPIT_UNIT__PORT="$mailpit_unit_port"
  MAILPIT_UNIT__SMTP_PORT="$mailpit_unit_smtp_port"
  MAILPIT_ROUTES__PORT="$mailpit_routes_port"
  MAILPIT_ROUTES__SMTP_PORT="$mailpit_routes_smtp_port"
  MAILPIT_INTEGRATION__PORT="$mailpit_integration_port"
  MAILPIT_INTEGRATION__SMTP_PORT="$mailpit_integration_smtp_port"

  export PGHOST PGPORT APP_PORT INTEGRATION_APP_PORT \
    MAILPIT__PORT MAILPIT__SMTP_PORT \
    MAILPIT_UNIT__PORT MAILPIT_UNIT__SMTP_PORT \
    MAILPIT_ROUTES__PORT MAILPIT_ROUTES__SMTP_PORT \
    MAILPIT_INTEGRATION__PORT MAILPIT_INTEGRATION__SMTP_PORT \
    PGUSER PGPASSWORD PGDATABASE

  if [ "${RESUME_STACK:-0}" -ne 1 ] && [ "${CHECK_ONLY:-0}" -eq 1 ]; then
    ensure_all_scoped_ports_free || return 1
  fi

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
        "  Set SERVER__SERVER_NAME to the host:port you browse locally (for example localhost:$app_port), or keep it blank to use request-based hosts."
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

write_runtime_scope_file() {
  if [ -z "${RUNTIME_SCOPE_FILE}" ]; then
    return 0
  fi

  cat > "${RUNTIME_SCOPE_FILE}" <<EOF
RUNTIME_SCOPE=${RUNTIME_SCOPE}
FMRIF_RUNTIME_SCOPE_OFFSET=${RUNTIME_SCOPE_OFFSET}
COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}
PGHOST=${PGHOST}
PGPORT=${PGPORT}
APP_PORT=${APP_PORT}
INTEGRATION_APP_PORT=${INTEGRATION_APP_PORT}
MAILPIT_APP_PORT=${MAILPIT__PORT}
MAILPIT_APP_SMTP_PORT=${MAILPIT__SMTP_PORT}
MAILPIT_UNIT_PORT=${MAILPIT_UNIT__PORT}
MAILPIT_UNIT_SMTP_PORT=${MAILPIT_UNIT__SMTP_PORT}
MAILPIT_ROUTES_PORT=${MAILPIT_ROUTES__PORT}
MAILPIT_ROUTES_SMTP_PORT=${MAILPIT_ROUTES__SMTP_PORT}
MAILPIT_INTEGRATION_PORT=${MAILPIT_INTEGRATION__PORT}
MAILPIT_INTEGRATION_SMTP_PORT=${MAILPIT_INTEGRATION__SMTP_PORT}
EOF
}

run_preflight() {
  derive_runtime_scope
  validate_runtime_env || return 1
  resolve_compose_project
  export FMRIF_COMPOSE_WRAPPER="run-compose.sh"
  prepare_compose_config

  # Keep container variables aligned even if only PG* values are set.
  : "${APP_PORT:=5051}"
  export APP_PORT INTEGRATION_APP_PORT PGHOST PGPORT \
    MAILPIT__PORT MAILPIT__SMTP_PORT \
    MAILPIT_UNIT__PORT MAILPIT_UNIT__SMTP_PORT \
    MAILPIT_ROUTES__PORT MAILPIT_ROUTES__SMTP_PORT \
    MAILPIT_INTEGRATION__PORT MAILPIT_INTEGRATION__SMTP_PORT \
    PGUSER PGPASSWORD PGDATABASE
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
  echo "  Integration test app port: $INTEGRATION_APP_PORT"
  echo "  DB (app-facing): $PGHOST:$PGPORT/$PGDATABASE"
  echo "  Mailpit app UI/SMTP: $MAILPIT__PORT/$MAILPIT__SMTP_PORT"
  echo "  Mailpit unit UI/SMTP: $MAILPIT_UNIT__PORT/$MAILPIT_UNIT__SMTP_PORT"
  echo "  Mailpit routes UI/SMTP: $MAILPIT_ROUTES__PORT/$MAILPIT_ROUTES__SMTP_PORT"
  echo "  Mailpit integration UI/SMTP: $MAILPIT_INTEGRATION__PORT/$MAILPIT_INTEGRATION__SMTP_PORT"
  echo "  Compose project: $COMPOSE_PROJECT_NAME"
  echo "  Runtime scope: $RUNTIME_SCOPE (offset=$RUNTIME_SCOPE_OFFSET)"
  echo "  DB (container): postgres wrapper exports POSTGRES_* from PG*"
  return 0
}

for arg in "$@"; do
  case "$arg" in
    --help|-h)
      show_help
      exit 0
      ;;
    --check)
      CHECK_ONLY=1
      ;;
    --no-app)
      START_NO_APP=1
      ;;
    --resume)
      RESUME_STACK=1
      ;;
    --reset)
      RESET_STACK=1
      ;;
    --remove)
      echo "ERROR: --remove has been replaced by --reset." >&2
      show_help
      exit 1
      ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      show_help
      exit 1
      ;;
  esac
done

if (( CHECK_ONLY )); then
  if (( START_NO_APP )) || (( RESUME_STACK )) || (( RESET_STACK )); then
    echo "ERROR: --check cannot be combined with --no-app, --resume, or --reset." >&2
    show_help
    exit 1
  fi
  run_preflight
  exit $?
fi

if (( RESUME_STACK )) && (( RESET_STACK )); then
  echo "ERROR: --resume cannot be combined with --reset." >&2
  show_help
  exit 1
fi

if (( RESET_STACK )) && (( CHECK_ONLY )); then
  echo "ERROR: --reset cannot be combined with --check." >&2
  show_help
  exit 1
fi

export FMRIF_COMPOSE_WRAPPER="run-compose.sh"
derive_runtime_scope
acquire_runtime_scope_file || exit 1
validate_runtime_env || exit 1

: "${APP_PORT:=5051}"
export APP_PORT INTEGRATION_APP_PORT PGHOST PGPORT \
  MAILPIT__PORT MAILPIT__SMTP_PORT \
  MAILPIT_UNIT__PORT MAILPIT_UNIT__SMTP_PORT \
  MAILPIT_ROUTES__PORT MAILPIT_ROUTES__SMTP_PORT \
  MAILPIT_INTEGRATION__PORT MAILPIT_INTEGRATION__SMTP_PORT \
  PGUSER PGPASSWORD PGDATABASE

resolve_compose_project
write_runtime_scope_file

echo "Using environment from $ENVFILE"
echo "  Runtime scope: $RUNTIME_SCOPE (offset=$RUNTIME_SCOPE_OFFSET)"
echo "  App port: $APP_PORT"
echo "  Integration test app port: $INTEGRATION_APP_PORT"
echo "  DB (app-facing): $PGHOST:$PGPORT/$PGDATABASE"
echo "  Mailpit app UI/SMTP: $MAILPIT__PORT/$MAILPIT__SMTP_PORT"
echo "  Mailpit unit UI/SMTP: $MAILPIT_UNIT__PORT/$MAILPIT_UNIT__SMTP_PORT"
echo "  Mailpit routes UI/SMTP: $MAILPIT_ROUTES__PORT/$MAILPIT_ROUTES__SMTP_PORT"
echo "  Mailpit integration UI/SMTP: $MAILPIT_INTEGRATION__PORT/$MAILPIT_INTEGRATION__SMTP_PORT"
echo "  Compose project: $COMPOSE_PROJECT_NAME"
echo "  Runtime scope file: $RUNTIME_SCOPE_FILE"
echo "  DB bootstrap aliases: PGUSER/PGPASSWORD/PGDATABASE in containerized postgres"

prepare_compose_config

stack_running=false
if compose_project_has_running_services; then
  stack_running=true
fi

if (( RESUME_STACK )); then
  echo "Resume mode enabled: restarting stack without wiping volumes."
  if [ "$stack_running" = true ]; then
    docker compose \
      --project-name "$COMPOSE_PROJECT_NAME" \
      --env-file "$COMPOSE_ENV_FILE" \
      down --remove-orphans
  fi
  if ! ensure_all_scoped_ports_free; then
    echo "ERROR: scoped runtime ports are not free for resume." >&2
    echo "ERROR: stop the conflicting host process(es), or choose a different FMRIF_RUNTIME_SCOPE." >&2
    exit 1
  fi
elif (( RESET_STACK )); then
  echo "Reset mode: replacing stack and wiping volumes."
  docker compose \
    --project-name "$COMPOSE_PROJECT_NAME" \
    --env-file "$COMPOSE_ENV_FILE" \
    down --volumes --remove-orphans
  if ! ensure_all_scoped_ports_free; then
    echo "ERROR: scoped runtime ports are still occupied after compose down." >&2
    echo "ERROR: stop the conflicting host process(es), or choose a different FMRIF_RUNTIME_SCOPE." >&2
    exit 1
  fi
else
  if [ "$stack_running" = true ]; then
    show_scope_running_guidance
    exit 0
  fi
  echo "Isolated mode: starting clean stack and wiping volumes for this scope."
  docker compose \
    --project-name "$COMPOSE_PROJECT_NAME" \
    --env-file "$COMPOSE_ENV_FILE" \
    down --volumes --remove-orphans
  if ! ensure_all_scoped_ports_free; then
    echo "ERROR: scoped runtime ports are still occupied after compose down." >&2
    echo "ERROR: stop the conflicting host process(es), or choose a different FMRIF_RUNTIME_SCOPE." >&2
    exit 1
  fi
fi

if (( START_NO_APP )); then
  echo "No-app mode: starting postgres + Mailpit services only."
  docker compose --project-name "$COMPOSE_PROJECT_NAME" --env-file "$COMPOSE_ENV_FILE" up --build postgres mailpit_app mailpit_unit mailpit_routes mailpit_integration
else
  docker compose --project-name "$COMPOSE_PROJECT_NAME" --env-file "$COMPOSE_ENV_FILE" up --build
fi
