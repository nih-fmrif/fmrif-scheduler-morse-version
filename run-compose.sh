#!/usr/bin/env bash
set -euo pipefail

: "${ENVFILE:=.env}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/scripts/runtime-scope.sh"

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

runtime_scope_resolve_compose_project() {
  local base_name="${SCHEDULER_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-scheduler}}"
  runtime_scope_set_compose_project_name "$base_name"
}

docker_available() {
  command -v docker >/dev/null 2>&1
}

compose_project_has_running_services() {
  local project_name="${1:-$COMPOSE_PROJECT_NAME}"
  if ! docker_available; then
    return 1
  fi
  docker ps \
    --filter "label=com.docker.compose.project=${project_name}" \
    --filter "status=running" \
    -q | grep -q .
}

resolve_scope_project_name() {
  local scope_name=$1
  local base_name=${2:-scheduler}
  local derived=$base_name

  if [ -z "$derived" ]; then
    derived="scheduler"
  fi

  if [ "$scope_name" != "default" ]; then
    case "$derived" in
      *-"${scope_name}")
        ;;
      *)
        derived="${derived}-${scope_name}"
        ;;
    esac
  fi

  runtime_scope_normalize_name "$derived"
}

SCOPE_INSPECT_METADATA_STATUS=""
SCOPE_INSPECT_STACK_STATE=""
SCOPE_INSPECT_PROJECT_NAME=""
SCOPE_INSPECT_METADATA_PROJECT_NAME=""
SCOPE_INSPECT_WORKTREE=""

reset_scope_inspection() {
  SCOPE_INSPECT_METADATA_STATUS="missing"
  SCOPE_INSPECT_STACK_STATE="unknown"
  SCOPE_INSPECT_PROJECT_NAME=""
  SCOPE_INSPECT_METADATA_PROJECT_NAME=""
  SCOPE_INSPECT_WORKTREE=""
}

inspect_scope_file() {
  local scope_file=$1
  local scope_name

  reset_scope_inspection
  scope_name="$(basename "$scope_file")"
  if [ ! -f "$scope_file" ]; then
    SCOPE_INSPECT_STACK_STATE="missing"
    return 1
  fi

  if ! runtime_scope_load_metadata "$scope_file"; then
    SCOPE_INSPECT_METADATA_STATUS="invalid"
    return 1
  fi

  SCOPE_INSPECT_METADATA_PROJECT_NAME="${RUNTIME_SCOPE_COMPOSE_PROJECT_NAME:-}"
  SCOPE_INSPECT_WORKTREE="${RUNTIME_SCOPE_WORKTREE_ROOT:-}"
  if [ -z "$SCOPE_INSPECT_METADATA_PROJECT_NAME" ]; then
    SCOPE_INSPECT_METADATA_STATUS="incomplete"
    SCOPE_INSPECT_STACK_STATE="untracked"
    return 0
  fi

  SCOPE_INSPECT_PROJECT_NAME="$SCOPE_INSPECT_METADATA_PROJECT_NAME"
  SCOPE_INSPECT_METADATA_STATUS="valid"
  SCOPE_INSPECT_PROJECT_NAME="$(resolve_scope_project_name "$scope_name" "$SCOPE_INSPECT_METADATA_PROJECT_NAME")"
  if ! docker_available; then
    SCOPE_INSPECT_STACK_STATE="unknown"
  elif compose_project_has_running_services "$SCOPE_INSPECT_PROJECT_NAME"; then
    SCOPE_INSPECT_STACK_STATE="running"
  else
    SCOPE_INSPECT_STACK_STATE="stopped"
  fi

  return 0
}

runtime_scope_current_worktree_root() {
  local root=""
  if command -v git >/dev/null 2>&1; then
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  fi
  printf '%s' "$root"
}

ensure_scope_worktree_match() {
  local scope="$1"
  local file_worktree="$2"
  local current_worktree=""
  if [ -z "$file_worktree" ]; then
    return 0
  fi

  current_worktree="$(runtime_scope_current_worktree_root)"
  if [ -z "$current_worktree" ]; then
    return 0
  fi

  if [ "$file_worktree" != "$current_worktree" ]; then
    echo "ERROR: scope '${scope}' is owned by a different worktree."
    echo "  scope metadata worktree: ${file_worktree}"
    echo "  current worktree: ${current_worktree}"
    echo "  Set FMRIF_RUNTIME_SCOPE to a different scope, or run from the owning worktree."
    return 1
  fi
  return 0
}

list_all_scopes() {
  local scope_files=()
  local scope_file
  local scope_name
  local running_count=0
  local stopped_count=0
  local untracked_count=0
  local unknown_count=0
  local invalid_count=0

  if [ ! -d "$RUNTIME_SCOPE_DIR" ]; then
    echo "No scope metadata directory found: ${RUNTIME_SCOPE_DIR}"
    return 0
  fi

  shopt -s nullglob
  scope_files=("${RUNTIME_SCOPE_DIR}"/*)
  shopt -u nullglob

  if [ ${#scope_files[@]} -eq 0 ]; then
    echo "No scope metadata files found in ${RUNTIME_SCOPE_DIR}."
    return 0
  fi

  for scope_file in "${scope_files[@]}"; do
    scope_name="$(basename "$scope_file")"
    if [ ! -f "$scope_file" ]; then
      continue
    fi
    inspect_scope_file "$scope_file" || true

    echo "Scope: ${scope_name}"
    echo "  compose_project: ${SCOPE_INSPECT_PROJECT_NAME:-<unset>}"
    if [ -n "$SCOPE_INSPECT_METADATA_PROJECT_NAME" ] && [ "$SCOPE_INSPECT_METADATA_PROJECT_NAME" != "$SCOPE_INSPECT_PROJECT_NAME" ]; then
      echo "  metadata_compose_project: ${SCOPE_INSPECT_METADATA_PROJECT_NAME}"
    fi
    echo "  worktree_root: ${SCOPE_INSPECT_WORKTREE:-<unset>}"
    echo "  metadata_status: ${SCOPE_INSPECT_METADATA_STATUS}"
    echo "  stack_state: ${SCOPE_INSPECT_STACK_STATE}"
    echo

    case "$SCOPE_INSPECT_METADATA_STATUS" in
      invalid)
        invalid_count=$((invalid_count + 1))
        ;;
    esac
    case "$SCOPE_INSPECT_STACK_STATE" in
      running)
        running_count=$((running_count + 1))
        ;;
      stopped)
        stopped_count=$((stopped_count + 1))
        ;;
      untracked)
        untracked_count=$((untracked_count + 1))
        ;;
      *)
        unknown_count=$((unknown_count + 1))
        ;;
    esac
  done

  echo "Summary: ${running_count} running, ${stopped_count} stopped, ${untracked_count} untracked, ${invalid_count} invalid, ${unknown_count} unknown."
}

teardown_scope_project() {
  local scope_name=$1
  local project_name=$2
  local stack_state=$3
  local action_label=$4

  echo "${action_label} scope '${scope_name}' (project=${project_name}, stack_state=${stack_state})."
  docker compose \
    --project-name "$project_name" \
    down --volumes --remove-orphans || true
}

clear_stale_scopes() {
  local scope_files=()
  local scope_file
  local scope_name
  local current_worktree
  local cleared_count=0
  local skipped_running_count=0

  if [ ! -d "$RUNTIME_SCOPE_DIR" ]; then
    echo "No scope metadata directory found: ${RUNTIME_SCOPE_DIR}"
    return 0
  fi

  shopt -s nullglob
  scope_files=("${RUNTIME_SCOPE_DIR}"/*)
  shopt -u nullglob

  if [ ${#scope_files[@]} -eq 0 ]; then
    echo "No scope metadata files found in ${RUNTIME_SCOPE_DIR}."
    return 0
  fi

  if ! docker_available; then
    echo "ERROR: docker is required for --clear-stale scope cleanup." >&2
    return 1
  fi

  for scope_file in "${scope_files[@]}"; do
    scope_name="$(basename "$scope_file")"
    if [ ! -f "$scope_file" ]; then
      continue
    fi

    inspect_scope_file "$scope_file" || true
    if [ "$SCOPE_INSPECT_STACK_STATE" = "running" ]; then
      echo "Skipping running scope '${scope_name}' (project=${SCOPE_INSPECT_PROJECT_NAME}). Use --wipe for the active scope or --clear-all for every scope."
      skipped_running_count=$((skipped_running_count + 1))
      continue
    fi

    if [ -n "$SCOPE_INSPECT_WORKTREE" ]; then
      current_worktree="$(runtime_scope_current_worktree_root)"
      if [ -n "$current_worktree" ] && [ "$SCOPE_INSPECT_WORKTREE" != "$current_worktree" ]; then
        echo "Warning: scope '${scope_name}' is owned by a different worktree (metadata: ${SCOPE_INSPECT_WORKTREE}); pruning stale metadata anyway."
      fi
    fi

    if [ -n "$SCOPE_INSPECT_PROJECT_NAME" ]; then
      teardown_scope_project "$scope_name" "$SCOPE_INSPECT_PROJECT_NAME" "$SCOPE_INSPECT_STACK_STATE" "Pruning stale"
    else
      echo "Removing stale metadata for scope '${scope_name}' (metadata_status=${SCOPE_INSPECT_METADATA_STATUS})."
    fi

    rm -f "$scope_file"
    cleared_count=$((cleared_count + 1))
  done

  echo "Pruned ${cleared_count} stale scope(s); skipped ${skipped_running_count} running scope(s)."
}

clear_all_scopes() {
  local scope_files=()
  local scope_file
  local scope_name
  local current_worktree
  local cleared_count=0

  if [ ! -d "$RUNTIME_SCOPE_DIR" ]; then
    echo "No scope metadata directory found: ${RUNTIME_SCOPE_DIR}"
    return 0
  fi

  shopt -s nullglob
  scope_files=("${RUNTIME_SCOPE_DIR}"/*)
  shopt -u nullglob

  if [ ${#scope_files[@]} -eq 0 ]; then
    echo "No scope metadata files found in ${RUNTIME_SCOPE_DIR}."
    return 0
  fi

  if ! docker_available; then
    echo "ERROR: docker is required for --clear-all scope cleanup." >&2
    return 1
  fi

  for scope_file in "${scope_files[@]}"; do
    scope_name="$(basename "$scope_file")"
    if [ ! -f "$scope_file" ]; then
      continue
    fi

    inspect_scope_file "$scope_file" || true
    if [ -n "$SCOPE_INSPECT_WORKTREE" ]; then
      current_worktree="$(runtime_scope_current_worktree_root)"
      if [ -n "$current_worktree" ] && [ "$SCOPE_INSPECT_WORKTREE" != "$current_worktree" ]; then
        echo "Warning: scope '${scope_name}' is owned by a different worktree (metadata: ${SCOPE_INSPECT_WORKTREE}); clearing it anyway."
      fi
    fi

    if [ -n "$SCOPE_INSPECT_PROJECT_NAME" ]; then
      teardown_scope_project "$scope_name" "$SCOPE_INSPECT_PROJECT_NAME" "$SCOPE_INSPECT_STACK_STATE" "Clearing"
    else
      echo "Clearing scope '${scope_name}' metadata only (metadata_status=${SCOPE_INSPECT_METADATA_STATUS})."
    fi

    rm -f "$scope_file"
    cleared_count=$((cleared_count + 1))
  done

  echo "Cleared ${cleared_count} scope(s) and removed their metadata files."
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
WIPE_SCOPE=0
LIST_ALL_SCOPES=0
CLEAR_STALE_SCOPES=0
CLEAR_ALL_SCOPES=0

show_help() {
  cat <<'EOF'
Usage:
  ./run-compose.sh --no-app            # recommended local dev: postgres + mailpit services only
  ./run-compose.sh --no-app --resume   # reuse existing postgres/mailpit data
  ./run-compose.sh --no-app --reset    # replace stack and wipe volumes
  ./run-compose.sh --wipe              # wipe active scope stack and metadata
  ./run-compose.sh --list-all          # list all scopes with metadata status and running/stopped stack state
  ./run-compose.sh --clear-stale       # remove stopped scopes and stale metadata; keep running stacks
  ./run-compose.sh --clear-all         # remove all known scope stacks and metadata, including running ones
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

validate_non_negative_int() {
  local value=$1
  local name=$2
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    echo "ERROR: ${name} must be a non-negative integer: ${value}" >&2
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

coalesce_session_cookie_name() {
  local base_cookie="${1:-}"
  local scope="${RUNTIME_SCOPE:-default}"
  if [ -z "${base_cookie}" ]; then
    base_cookie="dsid-${scope}"
  fi

  local suffix
  suffix="-${scope}"
  if [ "${scope}" = "default" ] || [[ "${base_cookie}" == *"${suffix}" ]]; then
    printf '%s' "$base_cookie"
    return 0
  fi

  printf '%s%s' "$base_cookie" "${suffix}"
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
  runtime_scope_load_metadata "$RUNTIME_SCOPE_FILE" || true

  PGHOST="${PGHOST:-$(runtime_scope_get_metadata PGHOST "localhost")}"
  PGPORT="${PGPORT:-$(runtime_scope_get_metadata PGPORT "5444")}"
  APP_PORT="${APP_PORT:-$(runtime_scope_get_metadata APP_PORT "5051")}"
  MAILPIT__PORT="${MAILPIT__PORT:-$(runtime_scope_get_metadata MAILPIT_APP_PORT "")}"
  MAILPIT__SMTP_PORT="${MAILPIT__SMTP_PORT:-$(runtime_scope_get_metadata MAILPIT_APP_SMTP_PORT "")}"
  PGDATABASE="${PGDATABASE:-$(runtime_scope_get_metadata PGDATABASE "fmrif_scheduler")}"
  PGUSER="${PGUSER:-$(runtime_scope_get_metadata PGUSER "postgres")}"
  PGPASSWORD="${PGPASSWORD:-$(runtime_scope_get_metadata PGPASSWORD "")}"

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

  if [[ "$MAIL__DEFAULT_SENDER" != *"@"* ]]; then
    echo "ERROR: MAIL__DEFAULT_SENDER must be a valid email address: $MAIL__DEFAULT_SENDER" >&2
    return 1
  fi

  if [[ ! "$PGPORT" =~ ^[0-9]+$ ]] || (( PGPORT < 1 || PGPORT > 65535 )); then
    echo "ERROR: PGPORT must be between 1 and 65535: $PGPORT" >&2
    return 1
  fi

  if [[ ! "$APP_PORT" =~ ^[0-9]+$ ]] || (( APP_PORT < 1 || APP_PORT > 65535 )); then
    echo "ERROR: APP_PORT must be between 1 and 65535: $APP_PORT" >&2
    return 1
  fi

  if [ -z "${MAILPIT__PORT}" ]; then
    MAILPIT__PORT=$((PGPORT + 1))
    if (( MAILPIT__PORT > 65535 )); then
      MAILPIT__PORT=8025
    fi
  elif [[ ! "$MAILPIT__PORT" =~ ^[0-9]+$ ]] || (( MAILPIT__PORT < 1 || MAILPIT__PORT > 65535 )); then
    echo "ERROR: MAILPIT__PORT must be between 1 and 65535: $MAILPIT__PORT" >&2
    return 1
  fi

  if [ "$MAILPIT__PORT" = "$APP_PORT" ] || [ "$MAILPIT__PORT" = "$PGPORT" ]; then
    echo "ERROR: MAILPIT__PORT must differ from APP_PORT ($APP_PORT) and PGPORT ($PGPORT)." >&2
    return 1
  fi

  if [ -z "${MAILPIT__SMTP_PORT}" ]; then
    MAILPIT__SMTP_PORT=$((PGPORT + 2))
    if (( MAILPIT__SMTP_PORT > 65535 )); then
      MAILPIT__SMTP_PORT=8026
    fi
  elif [[ ! "$MAILPIT__SMTP_PORT" =~ ^[0-9]+$ ]] || (( MAILPIT__SMTP_PORT < 1 || MAILPIT__SMTP_PORT > 65535 )); then
    echo "ERROR: MAILPIT__SMTP_PORT must be between 1 and 65535: $MAILPIT__SMTP_PORT" >&2
    return 1
  fi

  if [ "$MAILPIT__SMTP_PORT" = "$APP_PORT" ] || [ "$MAILPIT__SMTP_PORT" = "$PGPORT" ] || [ "$MAILPIT__SMTP_PORT" = "$MAILPIT__PORT" ]; then
    echo "ERROR: MAILPIT__SMTP_PORT must differ from APP_PORT ($APP_PORT), PGPORT ($PGPORT), and MAILPIT__PORT ($MAILPIT__PORT)." >&2
    return 1
  fi

  local scope_offset="${FMRIF_RUNTIME_SCOPE_OFFSET:-$(runtime_scope_get_metadata FMRIF_RUNTIME_SCOPE_OFFSET 0)}"
  validate_non_negative_int "$scope_offset" "FMRIF_RUNTIME_SCOPE_OFFSET"
  FMRIF_RUNTIME_SCOPE_OFFSET="${scope_offset}"
  export FMRIF_RUNTIME_SCOPE_OFFSET

  local base_pgport="${PGPORT}"
  local base_app_port="${APP_PORT}"
  local base_mailpit_port="${MAILPIT__PORT}"
  local base_mailpit_smtp_port="${MAILPIT__SMTP_PORT}"
  local base_integration_app_port
  local base_mailpit_unit_port
  local base_mailpit_unit_smtp_port
  local base_mailpit_routes_port
  local base_mailpit_routes_smtp_port
  local base_mailpit_integration_port
  local base_mailpit_integration_smtp_port
  SESSION__COOKIE_NAME="${SESSION__COOKIE_NAME:-$(runtime_scope_get_metadata SESSION__COOKIE_NAME "dsid-${RUNTIME_SCOPE}")}"
  SESSION__COOKIE_NAME="$(coalesce_session_cookie_name "$SESSION__COOKIE_NAME")"

  local scoped_pgport scoped_app_port
  local scoped_integration_app_port
  local scoped_mailpit_app_port scoped_mailpit_app_smtp_port
  local scoped_mailpit_unit_port scoped_mailpit_unit_smtp_port
  local scoped_mailpit_routes_port scoped_mailpit_routes_smtp_port
  local scoped_mailpit_integration_port scoped_mailpit_integration_smtp_port

  base_integration_app_port=$((base_app_port + 60))
  base_mailpit_unit_port=$((base_mailpit_port + 20))
  base_mailpit_unit_smtp_port=$((base_mailpit_smtp_port + 20))
  base_mailpit_routes_port=$((base_mailpit_port + 40))
  base_mailpit_routes_smtp_port=$((base_mailpit_smtp_port + 40))
  base_mailpit_integration_port=$((base_mailpit_port + 60))
  base_mailpit_integration_smtp_port=$((base_mailpit_smtp_port + 60))

  scoped_pgport=$((base_pgport + scope_offset))
  scoped_app_port=$((base_app_port + scope_offset))
  scoped_integration_app_port=$((base_integration_app_port + scope_offset))
  scoped_mailpit_app_port=$((base_mailpit_port + scope_offset))
  scoped_mailpit_app_smtp_port=$((base_mailpit_smtp_port + scope_offset))
  scoped_mailpit_unit_port=$((base_mailpit_unit_port + scope_offset))
  scoped_mailpit_unit_smtp_port=$((base_mailpit_unit_smtp_port + scope_offset))
  scoped_mailpit_routes_port=$((base_mailpit_routes_port + scope_offset))
  scoped_mailpit_routes_smtp_port=$((base_mailpit_routes_smtp_port + scope_offset))
  scoped_mailpit_integration_port=$((base_mailpit_integration_port + scope_offset))
  scoped_mailpit_integration_smtp_port=$((base_mailpit_integration_smtp_port + scope_offset))

  validate_port "$scoped_pgport" "PGPORT (scoped)" || return 1
  validate_port "$scoped_app_port" "APP_PORT (scoped)" || return 1
  validate_port "$scoped_integration_app_port" "INTEGRATION_APP_PORT (scoped)" || return 1
  validate_port "$scoped_mailpit_app_port" "MAILPIT__PORT (app scoped)" || return 1
  validate_port "$scoped_mailpit_app_smtp_port" "MAILPIT__SMTP_PORT (app scoped)" || return 1
  validate_port "$scoped_mailpit_unit_port" "MAILPIT_UNIT__PORT" || return 1
  validate_port "$scoped_mailpit_unit_smtp_port" "MAILPIT_UNIT__SMTP_PORT" || return 1
  validate_port "$scoped_mailpit_routes_port" "MAILPIT_ROUTES__PORT" || return 1
  validate_port "$scoped_mailpit_routes_smtp_port" "MAILPIT_ROUTES__SMTP_PORT" || return 1
  validate_port "$scoped_mailpit_integration_port" "MAILPIT_INTEGRATION__PORT" || return 1
  validate_port "$scoped_mailpit_integration_smtp_port" "MAILPIT_INTEGRATION__SMTP_PORT" || return 1

  ensure_ports_distinct \
    "$scoped_pgport" \
    "$scoped_app_port" \
    "$scoped_integration_app_port" \
    "$scoped_mailpit_app_port" \
    "$scoped_mailpit_app_smtp_port" \
    "$scoped_mailpit_unit_port" \
    "$scoped_mailpit_unit_smtp_port" \
    "$scoped_mailpit_routes_port" \
    "$scoped_mailpit_routes_smtp_port" \
    "$scoped_mailpit_integration_port" \
    "$scoped_mailpit_integration_smtp_port" || return 1

  PGPORT="$scoped_pgport"
  APP_PORT="$scoped_app_port"
  INTEGRATION_APP_PORT="$scoped_integration_app_port"
  MAILPIT__PORT="$scoped_mailpit_app_port"
  MAILPIT__SMTP_PORT="$scoped_mailpit_app_smtp_port"
  MAILPIT_UNIT__PORT="$scoped_mailpit_unit_port"
  MAILPIT_UNIT__SMTP_PORT="$scoped_mailpit_unit_smtp_port"
  MAILPIT_ROUTES__PORT="$scoped_mailpit_routes_port"
  MAILPIT_ROUTES__SMTP_PORT="$scoped_mailpit_routes_smtp_port"
  MAILPIT_INTEGRATION__PORT="$scoped_mailpit_integration_port"
  MAILPIT_INTEGRATION__SMTP_PORT="$scoped_mailpit_integration_smtp_port"

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
  export RUNTIME_SCOPE_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
  export RUNTIME_SCOPE_PGDATABASE="${PGDATABASE}"
  export RUNTIME_SCOPE_SCHEDULER_TEST_DB_NAME="${SCHEDULER_TEST_DB_NAME:-fmrif_scheduler_test}"
  export RUNTIME_SCOPE_SESSION__COOKIE_NAME="${SESSION__COOKIE_NAME}"
  export RUNTIME_SCOPE_AUTH_TEST__SHARED_SECRET="${AUTH_TEST__SHARED_SECRET:-}"

  export PGHOST PGPORT APP_PORT INTEGRATION_APP_PORT \
    MAILPIT__PORT MAILPIT__SMTP_PORT \
    MAILPIT_UNIT__PORT MAILPIT_UNIT__SMTP_PORT \
    MAILPIT_ROUTES__PORT MAILPIT_ROUTES__SMTP_PORT \
    MAILPIT_INTEGRATION__PORT MAILPIT_INTEGRATION__SMTP_PORT \
    PGUSER PGPASSWORD PGDATABASE SESSION__COOKIE_NAME

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

  local test_base_url="${TEST_BASE_URL:-}"
  if [[ "$test_base_url" =~ ^https?://(localhost|localhost\.localdomain|127\.0\.0\.1):([0-9]{1,5})(/.*)?$ ]]; then
    local test_base_port="${BASH_REMATCH[2]}"
    if [ "$test_base_port" != "$app_port" ]; then
      warning_lines+=(
        "TEST_BASE_URL=$test_base_url does not match APP_PORT=$app_port."
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
  runtime_scope_derive
  runtime_scope_load_metadata "$RUNTIME_SCOPE_FILE" || true
  validate_runtime_env || return 1
  runtime_scope_resolve_compose_project
  export RUNTIME_SCOPE_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
  runtime_scope_write_metadata "$RUNTIME_SCOPE_FILE"
  export FMRIF_COMPOSE_WRAPPER="run-compose.sh"
  prepare_compose_config

  # Keep container variables aligned even if only PG* values are set.
  : "${APP_PORT:=5051}"
  export APP_PORT INTEGRATION_APP_PORT PGHOST PGPORT \
    MAILPIT__PORT MAILPIT__SMTP_PORT \
    MAILPIT_UNIT__PORT MAILPIT_UNIT__SMTP_PORT \
    MAILPIT_ROUTES__PORT MAILPIT_ROUTES__SMTP_PORT \
    MAILPIT_INTEGRATION__PORT MAILPIT_INTEGRATION__SMTP_PORT \
    PGUSER PGPASSWORD PGDATABASE SESSION__COOKIE_NAME
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
    --wipe)
      WIPE_SCOPE=1
      ;;
    --list-all)
      LIST_ALL_SCOPES=1
      ;;
    --clear-stale)
      CLEAR_STALE_SCOPES=1
      ;;
    --clear-all)
      CLEAR_ALL_SCOPES=1
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
  if (( START_NO_APP )) || (( RESUME_STACK )) || (( RESET_STACK )) || (( WIPE_SCOPE )) || (( LIST_ALL_SCOPES )) || (( CLEAR_STALE_SCOPES )) || (( CLEAR_ALL_SCOPES )); then
    echo "ERROR: --check cannot be combined with --no-app, --resume, --reset, --wipe, --list-all, --clear-stale, or --clear-all." >&2
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

if (( LIST_ALL_SCOPES )) && (( START_NO_APP || RESUME_STACK || RESET_STACK || WIPE_SCOPE || CLEAR_STALE_SCOPES || CLEAR_ALL_SCOPES || CHECK_ONLY )); then
  echo "ERROR: --list-all cannot be combined with other workflow flags." >&2
  show_help
  exit 1
fi

if (( LIST_ALL_SCOPES )); then
  list_all_scopes
  exit 0
fi

if (( CLEAR_STALE_SCOPES )) && (( START_NO_APP || RESUME_STACK || RESET_STACK || WIPE_SCOPE || CHECK_ONLY || LIST_ALL_SCOPES || CLEAR_ALL_SCOPES )); then
  echo "ERROR: --clear-stale cannot be combined with other workflow flags." >&2
  show_help
  exit 1
fi

if (( CLEAR_STALE_SCOPES )); then
  clear_stale_scopes
  exit $?
fi

if (( CLEAR_ALL_SCOPES )) && (( START_NO_APP || RESUME_STACK || RESET_STACK || WIPE_SCOPE || CHECK_ONLY || LIST_ALL_SCOPES || CLEAR_STALE_SCOPES )); then
  echo "ERROR: --clear-all cannot be combined with other workflow flags." >&2
  show_help
  exit 1
fi

if (( CLEAR_ALL_SCOPES )); then
  clear_all_scopes
  exit $?
fi

if (( WIPE_SCOPE )) && (( START_NO_APP || RESUME_STACK || RESET_STACK || CHECK_ONLY || LIST_ALL_SCOPES || CLEAR_STALE_SCOPES || CLEAR_ALL_SCOPES )); then
  echo "ERROR: --wipe cannot be combined with --no-app, --resume, --reset, --check, --list-all, --clear-stale, or --clear-all." >&2
  show_help
  exit 1
fi

export FMRIF_COMPOSE_WRAPPER="run-compose.sh"
runtime_scope_derive
runtime_scope_load_metadata "$RUNTIME_SCOPE_FILE" || true
if ! ensure_scope_worktree_match "$RUNTIME_SCOPE" "${RUNTIME_SCOPE_WORKTREE_ROOT:-}"; then
  exit 1
fi
validate_runtime_env || exit 1

: "${APP_PORT:=5051}"
export APP_PORT INTEGRATION_APP_PORT PGHOST PGPORT \
  MAILPIT__PORT MAILPIT__SMTP_PORT \
  MAILPIT_UNIT__PORT MAILPIT_UNIT__SMTP_PORT \
  MAILPIT_ROUTES__PORT MAILPIT_ROUTES__SMTP_PORT \
  MAILPIT_INTEGRATION__PORT MAILPIT_INTEGRATION__SMTP_PORT \
  PGUSER PGPASSWORD PGDATABASE SESSION__COOKIE_NAME

runtime_scope_resolve_compose_project
export RUNTIME_SCOPE_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
runtime_scope_write_metadata "$RUNTIME_SCOPE_FILE"

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

if (( WIPE_SCOPE )); then
  echo "Wipe mode: removing scope '${RUNTIME_SCOPE}' stack and metadata."
  docker compose \
    --project-name "$COMPOSE_PROJECT_NAME" \
    --env-file "$COMPOSE_ENV_FILE" \
    down --volumes --remove-orphans || true
  rm -f "$RUNTIME_SCOPE_FILE"
  echo "Wiped runtime scope '${RUNTIME_SCOPE}'."
  exit 0
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
