#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/run-isolated-test-suite.sh <suite> <command ...>

Suites:
  unit
  routes
  integration

Behavior:
  - Loads .env defaults (without overriding already-exported vars).
  - Applies suite-scoped test database names.
  - Applies suite-scoped Mailpit ports/base URL.
  - Best-effort starts a dedicated Mailpit container for the suite.

Optional overrides:
  FMRIF_TEST_SUITE_PORT_OFFSET=<int>   # added to suite port offset
  FMRIF_TEST_APP_PORT=<int>          # integration base app port before suite/scope offset
  FMRIF_KEEP_SUITE_MAILPIT=true        # keep started mailpit container running
  FMRIF_INTEGRATION_DB_RESET=false     # integration only: skip DROP_DB bootstrap reset
  FMRIF_INTEGRATION_DB_REBUILD_TEMPLATE=true
  FMRIF_INTEGRATION_DB_TEMPLATE_NAME=<name>
EOF
}

if [ "$#" -lt 2 ]; then
  usage
  exit 1
fi

suite_raw="$1"
shift

case "${suite_raw}" in
  unit)
    suite="unit"
    suite_port_offset=20
    ;;
  routes|route)
    suite="routes"
    suite_port_offset=40
    ;;
  integration|integration-headed|integration-ci)
    suite="integration"
    suite_port_offset=60
    ;;
  *)
    echo "ERROR: unknown suite: ${suite_raw}" >&2
    usage
    exit 1
    ;;
esac

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
env_file="${ENVFILE:-${repo_root}/.env}"

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
      continue
    fi

    key="${line%%=*}"
    value="${line#*=}"
    key="$(trim "$key")"
    value="$(trim "$value")"
    if [[ -z "$key" ]]; then
      continue
    fi

    # Scope is always auto-derived by this wrapper; ignore dotenv overrides.
    case "$key" in
      FMRIF_RUNTIME_SCOPE)
        continue
        ;;
    esac

    if [[ -n "${!key+_}" ]]; then
      continue
    fi

    if [ "${#value}" -ge 2 ] && [ "${value:0:1}" = "${value: -1}" ] \
      && { [ "${value:0:1}" = "\"" ] || [ "${value:0:1}" = "'" ]; }; then
      value="${value:1:${#value}-2}"
    fi

    printf -v "$key" '%s' "$value"
    export "$key"
  done < "$file"
}

if [ -f "$env_file" ]; then
  load_env_file "$env_file"
fi

parse_int_or_default() {
  local raw=${1:-}
  local fallback=$2
  if [[ "$raw" =~ ^-?[0-9]+$ ]]; then
    printf '%s' "$raw"
  else
    printf '%s' "$fallback"
  fi
}

validate_port() {
  local port=$1
  local label=$2
  if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    echo "ERROR: invalid ${label} port: ${port}" >&2
    exit 1
  fi
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

short_hash8() {
  local raw=$1
  local hash
  hash="$(printf '%s' "$raw" | cksum | awk '{print $1}')"
  printf '%08x' $((hash % 2147483647))
}

normalize_pg_identifier() {
  local raw=$1
  local max_len=63
  if [ "${#raw}" -le "$max_len" ]; then
    printf '%s' "$raw"
    return 0
  fi
  local suffix
  suffix="$(short_hash8 "$raw")"
  local prefix_len=$((max_len - 1 - ${#suffix}))
  if (( prefix_len < 1 )); then
    printf '%s' "${suffix:0:max_len}"
    return 0
  fi
  printf '%s-%s' "${raw:0:prefix_len}" "$suffix"
}

sanitize_name() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | tr -cs 'a-z0-9' '-' \
    | sed 's/^-*//; s/-*$//'
}

sanitize_scope_tag() {
  local normalized hash max_len prefix_len
  max_len=24
  normalized="$(sanitize_name "$1")"
  if [ -z "$normalized" ]; then
    printf ''
    return 0
  fi
  if [ "${#normalized}" -le "$max_len" ]; then
    printf '%s' "$normalized"
    return 0
  fi
  hash="$(printf '%s' "$normalized" | cksum | awk '{printf "%06x", $1 % 16777216}')"
  prefix_len=$((max_len - 1 - ${#hash}))
  if (( prefix_len < 1 )); then
    printf '%s' "${hash:0:max_len}"
    return 0
  fi
  printf '%s-%s' "${normalized:0:prefix_len}" "$hash"
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

scope_hash_int31() {
  local raw=$1
  local hash
  hash="$(printf '%s' "$raw" | cksum | awk '{print $1}')"
  printf '%s' $((hash % 2147483647))
}

append_db_suffix_once() {
  local name=$1
  local suffix=$2
  if [ -z "$suffix" ] || [[ "$name" == *"_${suffix}" ]]; then
    printf '%s' "$name"
  else
    printf '%s_%s' "$name" "$suffix"
  fi
}

scope_source="runtime-scope"
runtime_scope_raw="${FMRIF_RUNTIME_SCOPE:-default}"
runtime_scope="$(sanitize_name "$runtime_scope_raw")"
if [ -z "$runtime_scope" ]; then
  runtime_scope="default"
fi
export FMRIF_RUNTIME_SCOPE="$runtime_scope"

raw_scope="$runtime_scope"

test_scope_tag="$(sanitize_scope_tag "${raw_scope}")"
if [ -z "$test_scope_tag" ]; then
  echo "ERROR: failed to derive a non-empty scope tag." >&2
  exit 1
fi
scope_offset="$(scope_hash_offset "$test_scope_tag")"

extra_offset="$(parse_int_or_default "${FMRIF_TEST_SUITE_PORT_OFFSET:-}" 0)"
suite_port_offset=$((suite_port_offset + extra_offset))

runtime_scope_file="/tmp/fmrif-scheduler-runtimes/${runtime_scope}"
scope_file_pgport=""
scope_file_app_port=""
scope_file_mailpit_app_port=""
scope_file_mailpit_app_smtp_port=""
scope_file_mailpit_unit_port=""
scope_file_mailpit_unit_smtp_port=""
scope_file_mailpit_routes_port=""
scope_file_mailpit_routes_smtp_port=""
scope_file_mailpit_integration_port=""
scope_file_mailpit_integration_smtp_port=""

load_runtime_scope_file() {
  local line key value
  if [ ! -f "$runtime_scope_file" ]; then
    return 0
  fi
  scope_source="runtime-scope-file"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [ -z "$line" ] && continue
    case "$line" in
      \#*)
        continue
        ;;
      *=*)
        ;;
      *)
        continue
        ;;
    esac
    key="${line%%=*}"
    value="${line#*=}"
    case "$key" in
      PGPORT) scope_file_pgport="$(parse_int_or_default "$value" "")" ;;
      APP_PORT) scope_file_app_port="$(parse_int_or_default "$value" "")" ;;
      MAILPIT_APP_PORT) scope_file_mailpit_app_port="$(parse_int_or_default "$value" "")" ;;
      MAILPIT_APP_SMTP_PORT) scope_file_mailpit_app_smtp_port="$(parse_int_or_default "$value" "")" ;;
      MAILPIT_UNIT_PORT) scope_file_mailpit_unit_port="$(parse_int_or_default "$value" "")" ;;
      MAILPIT_UNIT_SMTP_PORT) scope_file_mailpit_unit_smtp_port="$(parse_int_or_default "$value" "")" ;;
      MAILPIT_ROUTES_PORT) scope_file_mailpit_routes_port="$(parse_int_or_default "$value" "")" ;;
      MAILPIT_ROUTES_SMTP_PORT) scope_file_mailpit_routes_smtp_port="$(parse_int_or_default "$value" "")" ;;
      MAILPIT_INTEGRATION_PORT) scope_file_mailpit_integration_port="$(parse_int_or_default "$value" "")" ;;
      MAILPIT_INTEGRATION_SMTP_PORT) scope_file_mailpit_integration_smtp_port="$(parse_int_or_default "$value" "")" ;;
    esac
  done < "$runtime_scope_file"
}

load_runtime_scope_file

base_pgport_raw="$(parse_int_or_default "${PGPORT:-}" 5444)"
if [ -n "$scope_file_pgport" ]; then
  base_pgport="$scope_file_pgport"
else
  base_pgport=$((base_pgport_raw + scope_offset))
fi
validate_port "$base_pgport" "PGPORT"
export PGPORT="$base_pgport"

base_mailpit_ui_raw="$(parse_int_or_default "${MAILPIT__PORT:-}" $((base_pgport_raw + 1)))"
base_mailpit_smtp_raw="$(parse_int_or_default "${MAILPIT__SMTP_PORT:-}" $((base_pgport_raw + 2)))"
if [ -n "$scope_file_mailpit_app_port" ]; then
  base_mailpit_ui="$scope_file_mailpit_app_port"
else
  base_mailpit_ui=$((base_mailpit_ui_raw + scope_offset))
fi
if [ -n "$scope_file_mailpit_app_smtp_port" ]; then
  base_mailpit_smtp="$scope_file_mailpit_app_smtp_port"
else
  base_mailpit_smtp=$((base_mailpit_smtp_raw + scope_offset))
fi

case "$suite" in
  unit)
    if [ "$extra_offset" -eq 0 ] && [ -n "$scope_file_mailpit_unit_port" ] && [ -n "$scope_file_mailpit_unit_smtp_port" ]; then
      mailpit_port="$scope_file_mailpit_unit_port"
      mailpit_smtp_port="$scope_file_mailpit_unit_smtp_port"
    else
      mailpit_port=$((base_mailpit_ui + suite_port_offset))
      mailpit_smtp_port=$((base_mailpit_smtp + suite_port_offset))
    fi
    ;;
  routes)
    if [ "$extra_offset" -eq 0 ] && [ -n "$scope_file_mailpit_routes_port" ] && [ -n "$scope_file_mailpit_routes_smtp_port" ]; then
      mailpit_port="$scope_file_mailpit_routes_port"
      mailpit_smtp_port="$scope_file_mailpit_routes_smtp_port"
    else
      mailpit_port=$((base_mailpit_ui + suite_port_offset))
      mailpit_smtp_port=$((base_mailpit_smtp + suite_port_offset))
    fi
    ;;
  integration)
    if [ "$extra_offset" -eq 0 ] && [ -n "$scope_file_mailpit_integration_port" ] && [ -n "$scope_file_mailpit_integration_smtp_port" ]; then
      mailpit_port="$scope_file_mailpit_integration_port"
      mailpit_smtp_port="$scope_file_mailpit_integration_smtp_port"
    else
      mailpit_port=$((base_mailpit_ui + suite_port_offset))
      mailpit_smtp_port=$((base_mailpit_smtp + suite_port_offset))
    fi
    ;;
esac

validate_port "$mailpit_port" "MAILPIT__PORT"
validate_port "$mailpit_smtp_port" "MAILPIT__SMTP_PORT"

if [ "$mailpit_port" = "$mailpit_smtp_port" ]; then
  echo "ERROR: suite Mailpit API/SMTP ports must differ." >&2
  exit 1
fi

base_test_db_raw="${SCHEDULER_TEST_DB_NAME:-fmrif_scheduler_test}"
base_test_db_raw="$(append_db_suffix_once "$base_test_db_raw" "$test_scope_tag")"
if [[ "$base_test_db_raw" == *"_${suite}" ]]; then
  suite_test_db_raw="$base_test_db_raw"
else
  suite_test_db_raw="${base_test_db_raw}_${suite}"
fi

base_runtime_db_raw="${PGDATABASE:-fmrif_scheduler}"
base_runtime_db_raw="$(append_db_suffix_once "$base_runtime_db_raw" "$test_scope_tag")"
if [[ "$base_runtime_db_raw" == *"_${suite}" ]]; then
  suite_runtime_db_raw="$base_runtime_db_raw"
else
  suite_runtime_db_raw="${base_runtime_db_raw}_${suite}"
fi

suite_test_db="$(normalize_pg_identifier "$suite_test_db_raw")"
if [ "$suite_test_db" != "$suite_test_db_raw" ]; then
  echo "Normalized suite test DB name to ${suite_test_db} (Postgres identifier limit)." >&2
fi
suite_test_template_raw="${suite_test_db_raw}_template"
suite_test_template_db="$(normalize_pg_identifier "$suite_test_template_raw")"
if [ "$suite_test_template_db" != "$suite_test_template_raw" ]; then
  echo "Normalized suite test template DB name to ${suite_test_template_db} (Postgres identifier limit)." >&2
fi
if [ "$suite_test_template_db" = "$suite_test_db" ]; then
  echo "ERROR: normalized suite test DB/template names collided (${suite_test_db})." >&2
  exit 1
fi

suite_runtime_db="$(normalize_pg_identifier "$suite_runtime_db_raw")"
if [ "$suite_runtime_db" != "$suite_runtime_db_raw" ]; then
  echo "Normalized suite runtime DB name to ${suite_runtime_db} (Postgres identifier limit)." >&2
fi

export SCHEDULER_TEST_DB_NAME="$suite_test_db"
export SCHEDULER_TEST_DB_TEMPLATE_NAME="${suite_test_template_db}"
export MAILPIT__PORT="$mailpit_port"
export MAILPIT__SMTP_PORT="$mailpit_smtp_port"
export MAILPIT_API_BASE_URL="http://127.0.0.1:${MAILPIT__PORT}"
export PLAYWRIGHT_MAILPIT_API_BASE_URL="${MAILPIT_API_BASE_URL}"
export MAILPIT_SMTP_HOST="127.0.0.1"
export MAIL__SERVER="127.0.0.1"
export MAIL__PORT="${MAILPIT__SMTP_PORT}"
export MAIL__SUPPRESS_SEND="false"
export FMRIF_TEST_SUITE="${suite}"

if [ -z "${COVERAGE_FILE:-}" ]; then
  coverage_dir="${FMRIF_TEST_COVERAGE_DIR:-${repo_root}/.coverage-runs}"
  mkdir -p "$coverage_dir"
  export COVERAGE_FILE="${coverage_dir}/.coverage.${test_scope_tag}.${suite}"
fi

if [ "$suite" = "integration" ]; then
  export PGDATABASE="$suite_runtime_db"
  should_check_integration_port=true
  if [ -n "${FMRIF_TEST_APP_PORT:-}" ]; then
    base_app_port="$(parse_int_or_default "${FMRIF_TEST_APP_PORT}" 5051)"
  elif [ -n "$scope_file_app_port" ]; then
    base_app_port="$scope_file_app_port"
  else
    base_app_port_raw="$(parse_int_or_default "${APP_PORT:-5051}" 5051)"
    base_app_port=$((base_app_port_raw + scope_offset))
  fi
  isolated_app_port=$((base_app_port + suite_port_offset))
  validate_port "$isolated_app_port" "APP_PORT"
  export APP_PORT="$isolated_app_port"

  if [ -z "${PLAYWRIGHT_BASE_URL:-}" ] || [[ "${PLAYWRIGHT_BASE_URL}" =~ ^https?://(localhost|localhost\.localdomain|127\.0\.0\.1)(:[0-9]+)?(/.*)?$ ]]; then
    export PLAYWRIGHT_BASE_URL="http://localhost:${APP_PORT}"
  else
    should_check_integration_port=false
  fi

  if [ "$should_check_integration_port" = true ] && port_is_in_use "${APP_PORT}"; then
    echo "ERROR: integration APP_PORT is already in use: ${APP_PORT}" >&2
    echo "ERROR: choose a different FMRIF_RUNTIME_SCOPE." >&2
    exit 1
  fi
fi

is_truthy() {
  local value
  value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  case "$value" in
    1|true|yes|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

mailpit_available() {
  curl -fsS "${MAILPIT_API_BASE_URL}/api/v1/info" >/dev/null 2>&1
}

workspace_tag="$(sanitize_name "$(basename "${repo_root}")")"
scope_suffix=""
if [ -n "$test_scope_tag" ]; then
  scope_suffix="-${test_scope_tag}"
fi
mailpit_container_name="fmrif-mailpit-${workspace_tag}-${suite}${scope_suffix}"
started_mailpit=0
suite_lock_pid=""
suite_lock_log=""
suite_lock_sql=""
suite_lock_key=""
suite_lock_acquired=0

cleanup() {
  if [ "${suite_lock_acquired:-0}" -eq 1 ] && [ -n "${suite_lock_key:-}" ]; then
    PGPASSWORD="${PGPASSWORD:-}" psql \
      --no-psqlrc \
      -v ON_ERROR_STOP=1 \
      -h "${PGHOST:-localhost}" \
      -p "${PGPORT:-5444}" \
      -U "${PGUSER:-postgres}" \
      -d postgres \
      -Atq \
      -c "SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype = 'advisory' AND granted AND objsubid = 1 AND classid = 0 AND objid = ${suite_lock_key} AND pid <> pg_backend_pid()" \
      >/dev/null 2>&1 || true
  fi
  if [ -n "${suite_lock_pid:-}" ]; then
    kill "${suite_lock_pid}" >/dev/null 2>&1 || true
    wait "${suite_lock_pid}" 2>/dev/null || true
  fi
  if [ -n "${suite_lock_log:-}" ]; then
    rm -f "${suite_lock_log}" || true
  fi
  if [ -n "${suite_lock_sql:-}" ]; then
    rm -f "${suite_lock_sql}" || true
  fi
  if [ "$started_mailpit" -ne 1 ]; then
    return
  fi
  if is_truthy "${FMRIF_KEEP_SUITE_MAILPIT:-false}"; then
    return
  fi
  if command -v docker >/dev/null 2>&1; then
    docker rm -f "$mailpit_container_name" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

acquire_suite_scope_lock() {
  local lock_seed lock_key hold_seconds rc
  lock_seed="${PGHOST:-localhost}|${PGPORT:-5444}|${suite}|${SCHEDULER_TEST_DB_NAME}|${SCHEDULER_TEST_DB_TEMPLATE_NAME}|${MAILPIT__PORT}|${MAILPIT__SMTP_PORT}|${PGDATABASE:-}|${APP_PORT:-}"
  lock_key="$(scope_hash_int31 "${lock_seed}")"
  suite_lock_key="$lock_key"
  hold_seconds=2147483
  suite_lock_log="$(mktemp)"
  suite_lock_sql="$(mktemp)"
  cat > "${suite_lock_sql}" <<EOF
\set ON_ERROR_STOP on
SELECT CASE WHEN pg_try_advisory_lock(${lock_key}) THEN 1 ELSE 0 END AS lock_acquired \gset
\if :lock_acquired
SELECT pg_sleep(${hold_seconds});
\else
\echo LOCK_BUSY
\quit
\endif
EOF

  PGPASSWORD="${PGPASSWORD:-}" psql \
    --no-psqlrc \
    -v ON_ERROR_STOP=1 \
    -h "${PGHOST:-localhost}" \
    -p "${PGPORT:-5444}" \
    -U "${PGUSER:-postgres}" \
    -d postgres \
    -f "${suite_lock_sql}" \
    >"${suite_lock_log}" 2>&1 &
  suite_lock_pid=$!
  sleep 0.25

  if ! kill -0 "${suite_lock_pid}" >/dev/null 2>&1; then
    rc=0
    wait "${suite_lock_pid}" || rc=$?
    if grep -q '^LOCK_BUSY$' "${suite_lock_log}"; then
      echo "ERROR: suite lock is already held for suite=${suite} scope=${test_scope_tag}." >&2
      echo "ERROR: wait for the active same-suite run to finish before starting another." >&2
    else
      echo "ERROR: failed to acquire suite lock for suite=${suite} scope=${test_scope_tag}." >&2
      if [ -s "${suite_lock_log}" ]; then
        sed 's/^/  /' "${suite_lock_log}" >&2
      fi
    fi
    exit 1
  fi

  suite_lock_acquired=1
}

acquire_suite_scope_lock

ensure_suite_mailpit() {
  if mailpit_available; then
    return 0
  fi

  if port_is_in_use "${MAILPIT__PORT}" || port_is_in_use "${MAILPIT__SMTP_PORT}"; then
    echo "ERROR: suite Mailpit ports are already in use but not reachable as Mailpit (${MAILPIT__PORT}/${MAILPIT__SMTP_PORT})." >&2
    echo "ERROR: choose a different FMRIF_RUNTIME_SCOPE." >&2
    exit 1
  fi

  if ! command -v docker >/dev/null 2>&1; then
    echo "WARN: docker unavailable; dedicated Mailpit not started for ${suite}." >&2
    return 0
  fi

  docker rm -f "$mailpit_container_name" >/dev/null 2>&1 || true
  if ! docker run \
    --detach \
    --rm \
    --name "$mailpit_container_name" \
    --publish "${MAILPIT__PORT}:8025" \
    --publish "${MAILPIT__SMTP_PORT}:1025" \
    axllent/mailpit:latest >/dev/null; then
    echo "WARN: failed to start dedicated Mailpit container ${mailpit_container_name}." >&2
    echo "WARN: continuing; Mailpit-dependent tests may skip/fail." >&2
    return 0
  fi
  started_mailpit=1

  local attempts=30
  while (( attempts > 0 )); do
    if mailpit_available; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 0.2
  done

  echo "WARN: dedicated Mailpit did not become ready at ${MAILPIT_API_BASE_URL}." >&2
  echo "WARN: continuing; Mailpit-dependent tests may skip/fail." >&2
}

ensure_suite_mailpit

hash_stream() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | awk '{print $1}'
    return 0
  fi
  cksum | awk '{print $1 ":" $2}'
}

normalize_pg_database_name() {
  normalize_pg_identifier "$1"
}

sql_ident() {
  local raw=$1
  raw="${raw//\"/\"\"}"
  printf '"%s"' "$raw"
}

sql_literal() {
  local raw=$1
  raw="${raw//\'/\'\'}"
  printf "'%s'" "$raw"
}

hash_file() {
  local file=$1
  if [ ! -f "$file" ]; then
    echo "missing"
    return 0
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
    return 0
  fi
  cksum "$file" | awk '{print $1 ":" $2}'
}

integration_template_fingerprint() {
  local sql_dir="${repo_root}/sql"
  local init_script="${sql_dir}/000-init.sh"
  local seed_dump="${SQL_SEED_DUMP_FILE:-${sql_dir}/003-import-data.sql}"
  local user_dept_csv="${SQL_USER_DEPT_CSV:-${sql_dir}/user-dept.csv}"
  local dev_dept_csv="${SQL_DEV_DEPT_CSV:-${sql_dir}/dev-dept.csv}"
  local devperm_csv="${SQL_DEVPERM_CSV:-${sql_dir}/devperm.csv}"
  local additive_layers="${SQL_ADDITIVE_LAYER_FILES:-}"

  if [ -z "$additive_layers" ] && [ -f "${sql_dir}/900-import-new-data.sql" ]; then
    additive_layers="${sql_dir}/900-import-new-data.sql"
  fi

  {
    echo "suite=integration"
    echo "init_script=${init_script}:$(hash_file "${init_script}")"

    while IFS= read -r migration; do
      [ -z "$migration" ] && continue
      echo "migration=${migration}:$(hash_file "${migration}")"
    done < <(find "${sql_dir}" -maxdepth 1 -type f -name '[0-9][0-9][0-9]-*.sql' | sort)

    for file in "${seed_dump}" "${user_dept_csv}" "${dev_dept_csv}" "${devperm_csv}"; do
      echo "seed=${file}:$(hash_file "${file}")"
    done

    echo "additive_layers=${additive_layers}"
    if [ -n "$additive_layers" ]; then
      local oldifs="$IFS"
      IFS=','
      read -r -a layer_files <<< "$additive_layers"
      IFS="$oldifs"
      local layer
      for layer in "${layer_files[@]}"; do
        layer="$(trim "$layer")"
        [ -z "$layer" ] && continue
        echo "layer=${layer}:$(hash_file "${layer}")"
      done
    fi
  } | hash_stream
}

pg_admin_query() {
  local sql_text=$1
  shift || true
  PGPASSWORD="${PGPASSWORD:-}" psql \
    --no-psqlrc \
    -v ON_ERROR_STOP=1 \
    -h "${PGHOST:-localhost}" \
    -p "${PGPORT:-5444}" \
    -U "${PGUSER:-postgres}" \
    -d postgres \
    -Atq \
    "$@" \
    -c "$sql_text"
}

pg_db_exists() {
  local db_name=$1
  local value
  value="$(pg_admin_query "SELECT 1 FROM pg_database WHERE datname = $(sql_literal "$db_name")")"
  [ "$(printf '%s' "$value" | tr -d '[:space:]')" = "1" ]
}

pg_db_comment() {
  local db_name=$1
  pg_admin_query "SELECT COALESCE(shobj_description(oid, 'pg_database'), '') FROM pg_database WHERE datname = $(sql_literal "$db_name")" | head -n 1
}

drop_pg_database() {
  local db_name=$1
  local db_ident
  local db_lit
  db_ident="$(sql_ident "$db_name")"
  db_lit="$(sql_literal "$db_name")"
  if ! pg_db_exists "$db_name"; then
    return 0
  fi

  pg_admin_query \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = ${db_lit} AND pid <> pg_backend_pid()" >/dev/null || true

  pg_admin_query \
    "ALTER DATABASE ${db_ident} WITH IS_TEMPLATE false" >/dev/null || true

  pg_admin_query \
    "DROP DATABASE ${db_ident}" >/dev/null
}

create_pg_database_from_template() {
  local db_name=$1
  local template_name=$2
  local db_ident
  local template_ident
  db_ident="$(sql_ident "$db_name")"
  template_ident="$(sql_ident "$template_name")"

  pg_admin_query \
    "CREATE DATABASE ${db_ident} TEMPLATE ${template_ident}" >/dev/null
}

mark_pg_database_template() {
  local db_name=$1
  local marker=$2
  local db_ident
  local db_lit
  local marker_lit
  db_ident="$(sql_ident "$db_name")"
  db_lit="$(sql_literal "$db_name")"
  marker_lit="$(sql_literal "$marker")"

  pg_admin_query \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = ${db_lit} AND pid <> pg_backend_pid()" >/dev/null || true

  pg_admin_query \
    "ALTER DATABASE ${db_ident} WITH IS_TEMPLATE true" >/dev/null
  pg_admin_query \
    "COMMENT ON DATABASE ${db_ident} IS ${marker_lit}" >/dev/null
}

ensure_integration_template_database() {
  local runtime_db=$1
  local init_script="${repo_root}/sql/000-init.sh"
  if [ ! -f "$init_script" ]; then
    echo "ERROR: missing SQL bootstrap script for integration suite: ${init_script}" >&2
    exit 1
  fi

  local template_raw="${FMRIF_INTEGRATION_DB_TEMPLATE_NAME:-${runtime_db}_template}"
  local template_db
  template_db="$(normalize_pg_database_name "$template_raw")"
  if [ "$template_db" != "$template_raw" ]; then
    echo "Normalized integration template DB name to ${template_db} (Postgres identifier limit)." >&2
  fi
  if [ "$template_db" = "$runtime_db" ]; then
    echo "ERROR: FMRIF_INTEGRATION_DB_TEMPLATE_NAME must differ from PGDATABASE (${runtime_db})" >&2
    exit 1
  fi

  local marker="integration-template:$(integration_template_fingerprint)"
  local rebuild_template=false
  if is_truthy "${FMRIF_INTEGRATION_DB_REBUILD_TEMPLATE:-false}"; then
    rebuild_template=true
  fi

  local template_exists=false
  if pg_db_exists "$template_db"; then
    template_exists=true
  fi

  local template_comment=""
  if [ "$template_exists" = true ]; then
    template_comment="$(pg_db_comment "$template_db")"
  fi

  if [ "$rebuild_template" = true ] || [ "$template_exists" = false ] || [ "$template_comment" != "$marker" ]; then
    if [ "$template_exists" = true ]; then
      drop_pg_database "$template_db"
    fi

    local previous_pgdatabase="${PGDATABASE}"
    local previous_drop_db="${DROP_DB-}"
    export PGDATABASE="$template_db"
    export DROP_DB=true

    echo "Bootstrapping integration template database ${template_db}..."
    if ! bash "$init_script"; then
      echo "ERROR: failed to bootstrap integration template database ${template_db}" >&2
      exit 1
    fi

    export PGDATABASE="$previous_pgdatabase"
    if [ -n "${previous_drop_db}" ]; then
      export DROP_DB="${previous_drop_db}"
    else
      unset DROP_DB
    fi
  fi

  mark_pg_database_template "$template_db" "$marker"
  INTEGRATION_TEMPLATE_DB_NAME="$template_db"
}

ensure_integration_database() {
  if [ "$suite" != "integration" ]; then
    return 0
  fi

  local runtime_db="${PGDATABASE}"

  local reset_db=true
  if ! is_truthy "${FMRIF_INTEGRATION_DB_RESET:-true}"; then
    reset_db=false
  fi

  if [ "$reset_db" = "false" ] && pg_db_exists "${runtime_db}"; then
    echo "Preserving integration database ${runtime_db} (FMRIF_INTEGRATION_DB_RESET=false)."
    return 0
  fi

  ensure_integration_template_database "${runtime_db}"

  echo "Refreshing integration database ${runtime_db} from template ${INTEGRATION_TEMPLATE_DB_NAME}..."
  drop_pg_database "${runtime_db}"
  create_pg_database_from_template "${runtime_db}" "${INTEGRATION_TEMPLATE_DB_NAME}"
}

ensure_integration_database

echo "Running ${suite} suite with isolated test resources:"
if [ -n "$runtime_scope" ]; then
  echo "  FMRIF_RUNTIME_SCOPE=${runtime_scope}"
  echo "  FMRIF_RUNTIME_SCOPE_SOURCE=${scope_source}"
fi
echo "  SCHEDULER_TEST_DB_NAME=${SCHEDULER_TEST_DB_NAME}"
echo "  SCHEDULER_TEST_DB_TEMPLATE_NAME=${SCHEDULER_TEST_DB_TEMPLATE_NAME}"
echo "  MAILPIT_API_BASE_URL=${MAILPIT_API_BASE_URL}"
echo "  MAILPIT__SMTP_PORT=${MAILPIT__SMTP_PORT}"
if [ "$suite" = "integration" ]; then
  echo "  PGDATABASE=${PGDATABASE}"
  echo "  APP_PORT=${APP_PORT}"
  echo "  PLAYWRIGHT_BASE_URL=${PLAYWRIGHT_BASE_URL:-}"
fi

"$@"
