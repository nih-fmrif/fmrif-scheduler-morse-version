#!/usr/bin/env bash
set -euo pipefail

sample_file=".env.sample.local"
target_env_file=".env"
secret_placeholder="__GENERATE_AUTH_TEST_SECRET__"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/scripts/runtime-scope.sh"

if [ ! -f "$sample_file" ]; then
  echo "ERROR: $sample_file was not found. Create it or copy from the template." >&2
  exit 1
fi

runtime_scope_derive
runtime_scope_load_metadata "$RUNTIME_SCOPE_FILE" || true

declare -A existing_env

trim() {
  local value=$1
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

is_var_set() {
  local name=$1
  [[ -v "$name" ]]
}

is_placeholder() {
  local value=$1
  [[ "$value" == __*__ ]]
}

load_existing_env() {
  local file=$1
  local line key value
  if [ ! -f "$file" ]; then
    return 0
  fi

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
    if [ -z "$key" ]; then
      continue
    fi
    if [ ${#value} -ge 2 ] && [ "${value:0:1}" = "${value: -1}" ] \
      && { [ "${value:0:1}" = '"' ] || [ "${value:0:1}" = "'" ]; }; then
      value="${value:1:${#value}-2}"
    fi
    existing_env["$key"]="$value"
  done < "$file"
}

normalize_int_candidate() {
  local value=$1
  local label=$2
  if [ -z "$value" ] || is_placeholder "$value"; then
    printf ''
    return 0
  fi
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    printf '%s' "$value"
    return 0
  fi
  echo "ERROR: $label must be numeric: $value" >&2
  exit 1
}

resolve_candidate() {
  local key=$1

  if is_var_set "$key"; then
    printf '%s' "${!key}"
    return 0
  fi
  if [ -n "${existing_env[$key]+x}" ]; then
    printf '%s' "${existing_env[$key]}"
    return 0
  fi
  printf '%s' "$(runtime_scope_get_metadata "$key" "")"
}

validate_port() {
  local port=$1
  local name=$2
  if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    echo "ERROR: $name must be between 1 and 65535: $port" >&2
    exit 1
  fi
}

validate_positive_int() {
  local value=$1
  local name=$2
  if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < 1 )); then
    echo "ERROR: $name must be a positive integer: $value" >&2
    exit 1
  fi
}

pick_available_port() {
  local preferred=$1
  local label=$2
  shift 2
  local excluded=("$@")
  local candidate
  local attempts=0
  local scan

  validate_port "$preferred" "$label preferred port"

  if ! port_in_use "$preferred" && ! contains "$preferred" "${excluded[@]}"; then
    printf '%s' "$preferred"
    return 0
  fi

  while (( attempts < 256 )); do
    candidate=$(( (RANDOM * 32768 + RANDOM) % 45536 + 20000 ))
    if contains "$candidate" "${excluded[@]}"; then
      attempts=$((attempts + 1))
      continue
    fi
    if ! port_in_use "$candidate"; then
      printf '%s' "$candidate"
      return 0
    fi
    attempts=$((attempts + 1))
  done

  for (( scan = 20000; scan <= 65535; scan += 1 )); do
    if contains "$scan" "${excluded[@]}"; then
      continue
    fi
    if ! port_in_use "$scan"; then
      printf '%s' "$scan"
      return 0
    fi
  done

  echo "ERROR: no available port found for $label" >&2
  exit 1
}

contains() {
  local needle=$1
  shift
  local candidate
  for candidate in "$@"; do
    if [ "$candidate" = "$needle" ]; then
      return 0
    fi
  done
  return 1
}

port_in_use() {
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
  else
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

generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
    return
  fi

  local python_cmd=""
  if command -v python3 >/dev/null 2>&1; then
    python_cmd="python3"
  elif command -v python >/dev/null 2>&1; then
    python_cmd="python"
  else
    echo "ERROR: openssl and python are both unavailable for secret generation." >&2
    exit 1
  fi

  "$python_cmd" - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}

coalesce_session_cookie_name() {
  local base_cookie="${1:-}"
  local scope="${RUNTIME_SCOPE:-default}"
  if [ -z "${base_cookie}" ]; then
    base_cookie="dsid-${scope}"
  fi

  local suffix
  suffix="-${scope}"
  if [ "${scope}" = "default" ] || [[ "$base_cookie" == *"${suffix}" ]]; then
    printf '%s' "$base_cookie"
    return 0
  fi

  printf '%s%s' "$base_cookie" "$suffix"
}

pick_missing_secret() {
  local candidate="${1:-}"
  AUTH_TEST__SHARED_SECRET_GENERATED=0
  if is_var_set "AUTH_TEST__SHARED_SECRET"; then
    if [ -n "${AUTH_TEST__SHARED_SECRET}" ] && ! is_placeholder "${AUTH_TEST__SHARED_SECRET}"; then
      printf '%s' "$AUTH_TEST__SHARED_SECRET"
      return
    fi
    AUTH_TEST__SHARED_SECRET_GENERATED=1
    generate_secret
    return
  fi

  if [ -n "$candidate" ] && ! is_placeholder "$candidate" && [ "$candidate" != "$secret_placeholder" ]; then
    printf '%s' "$candidate"
    return
  fi
  AUTH_TEST__SHARED_SECRET_GENERATED=1
  generate_secret
}

load_existing_env "$target_env_file"

declare -A final_values

scope_base="${RUNTIME_SCOPE:-default}"

app_candidate="$(resolve_candidate APP_PORT)"
app_port=""
if [ -n "${app_candidate}" ]; then
  app_port="$(normalize_int_candidate "$app_candidate" APP_PORT)"
fi
if [ -z "${app_port}" ]; then
  app_port="$(pick_available_port 5051 "APP_PORT")"
fi
validate_port "$app_port" "APP_PORT"

pg_port_candidate="$(resolve_candidate PGPORT)"
pg_port=""
if [ -n "${pg_port_candidate}" ]; then
  pg_port="$(normalize_int_candidate "$pg_port_candidate" PGPORT)"
fi
if [ -z "${pg_port}" ]; then
  pg_port="$(pick_available_port 5444 "PGPORT" "$app_port")"
fi
validate_port "$pg_port" "PGPORT"

if [ "$pg_port" = "$app_port" ]; then
  echo "ERROR: PGPORT must differ from APP_PORT ($app_port)." >&2
  exit 1
fi

mailpit_port_candidate="$(resolve_candidate MAILPIT__PORT)"
mailpit_port=""
if [ -n "${mailpit_port_candidate}" ]; then
  mailpit_port="$(normalize_int_candidate "$mailpit_port_candidate" "MAILPIT__PORT")"
fi
if [ -z "${mailpit_port}" ]; then
  preferred="$((pg_port + 1))"
  if (( preferred > 65535 )); then
    preferred=8025
  fi
  mailpit_port="$(pick_available_port "$preferred" "MAILPIT__PORT" "$app_port" "$pg_port")"
fi
validate_port "$mailpit_port" "MAILPIT__PORT"

mailpit_smtp_port_candidate="$(resolve_candidate MAILPIT__SMTP_PORT)"
mailpit_smtp_port=""
if [ -n "${mailpit_smtp_port_candidate}" ]; then
  mailpit_smtp_port="$(normalize_int_candidate "$mailpit_smtp_port_candidate" "MAILPIT__SMTP_PORT")"
fi
if [ -z "${mailpit_smtp_port}" ]; then
  preferred="$((pg_port + 2))"
  if (( preferred > 65535 )); then
    preferred=8026
  fi
  mailpit_smtp_port="$(pick_available_port "$preferred" "MAILPIT__SMTP_PORT" "$app_port" "$pg_port" "$mailpit_port")"
fi
validate_port "$mailpit_smtp_port" "MAILPIT__SMTP_PORT"

if [ "$mailpit_port" = "$mailpit_smtp_port" ] || [ "$mailpit_port" = "$app_port" ] || [ "$mailpit_port" = "$pg_port" ]; then
  echo "ERROR: MAILPIT__PORT must differ from APP_PORT and PGPORT." >&2
  exit 1
fi
if [ "$mailpit_smtp_port" = "$app_port" ] || [ "$mailpit_smtp_port" = "$pg_port" ] || [ "$mailpit_smtp_port" = "$mailpit_port" ]; then
  echo "ERROR: MAILPIT__SMTP_PORT must differ from APP_PORT, PGPORT, and MAILPIT__PORT." >&2
  exit 1
fi

compose_candidate="$(resolve_candidate COMPOSE_PROJECT_NAME)"
if [ -n "$compose_candidate" ] && ! is_placeholder "$compose_candidate"; then
  compose_project="$compose_candidate"
else
  compose_project="scheduler"
fi
pg_host="$(resolve_candidate PGHOST)"
if [ -z "$pg_host" ] || is_placeholder "$pg_host"; then
  pg_host="localhost"
fi
pg_user="$(resolve_candidate PGUSER)"
if [ -z "$pg_user" ] || is_placeholder "$pg_user"; then
  pg_user="postgres"
fi
pg_password="$(resolve_candidate PGPASSWORD)"
if [ -z "$pg_password" ] || is_placeholder "$pg_password"; then
  pg_password="password"
fi

pg_database_candidate="$(resolve_candidate PGDATABASE)"
if [ -n "$pg_database_candidate" ] && ! is_placeholder "$pg_database_candidate"; then
  pg_database="$pg_database_candidate"
else
  pg_database="fmrif_scheduler_${scope_base}"
fi

test_db_candidate="$(resolve_candidate SCHEDULER_TEST_DB_NAME)"
if [ -n "$test_db_candidate" ] && ! is_placeholder "$test_db_candidate"; then
  test_db_name="$test_db_candidate"
else
  test_db_name="fmrif_scheduler_test_${scope_base}"
fi

session_cookie_candidate="$(resolve_candidate SESSION__COOKIE_NAME)"
if [ -n "$session_cookie_candidate" ] && ! is_placeholder "$session_cookie_candidate"; then
  session_cookie_name="$(coalesce_session_cookie_name "$session_cookie_candidate")"
else
  session_cookie_name="$(coalesce_session_cookie_name "")"
fi

session_cookie_secure="$(resolve_candidate SESSION__COOKIE_SECURE)"
if is_placeholder "$session_cookie_secure"; then
  session_cookie_secure=""
fi
session_cookie_secure="${session_cookie_secure:-false}"

security_auth_rate_limit_max_requests="$(resolve_candidate SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS)"
if is_placeholder "$security_auth_rate_limit_max_requests"; then
  security_auth_rate_limit_max_requests=""
fi
security_auth_rate_limit_max_requests="${security_auth_rate_limit_max_requests:-120}"

server_name="$(resolve_candidate SERVER__SERVER_NAME)"
if is_placeholder "$server_name"; then
  server_name=""
fi
server_name="${server_name:-}"
mail_default_sender_candidate="$(resolve_candidate MAIL__DEFAULT_SENDER)"
if [ -n "$mail_default_sender_candidate" ] && ! is_placeholder "$mail_default_sender_candidate"; then
  mail_default_sender="$mail_default_sender_candidate"
else
  mail_default_sender="scheduler-${scope_base}@localhost.localdomain"
fi

if [[ "$mail_default_sender" != *"@"* ]]; then
  echo "ERROR: MAIL__DEFAULT_SENDER must be an email address: $mail_default_sender" >&2
  exit 1
fi

auth_secret_candidate="$(resolve_candidate AUTH_TEST__SHARED_SECRET)"
auth_test_secret="$(pick_missing_secret "$auth_secret_candidate")"

validate_positive_int "$security_auth_rate_limit_max_requests" "SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS"

final_values[APP_PORT]="$app_port"
final_values[PGHOST]="$pg_host"
final_values[PGPORT]="$pg_port"
final_values[MAILPIT__PORT]="$mailpit_port"
final_values[MAILPIT__SMTP_PORT]="$mailpit_smtp_port"
final_values[COMPOSE_PROJECT_NAME]="$compose_project"
final_values[PGUSER]="$pg_user"
final_values[PGPASSWORD]="$pg_password"
final_values[PGDATABASE]="$pg_database"
final_values[SCHEDULER_TEST_DB_NAME]="$test_db_name"
final_values[SESSION__COOKIE_NAME]="$session_cookie_name"
final_values[SESSION__COOKIE_SECURE]="$session_cookie_secure"
final_values[SERVER__SERVER_NAME]="$server_name"
final_values[MAIL__DEFAULT_SENDER]="$mail_default_sender"
final_values[SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS]="$security_auth_rate_limit_max_requests"
final_values[AUTH_TEST__SHARED_SECRET]="$auth_test_secret"
final_values[MAIL__SERVER]="localhost"
final_values[MAIL__PORT]="$mailpit_smtp_port"
final_values[MAIL__SUPPRESS_SEND]="${MAIL__SUPPRESS_SEND:-false}"

input_file="$sample_file"
if [ -f "$target_env_file" ]; then
  input_file="$target_env_file"
fi

tmp_env="$(mktemp)"
> "$tmp_env"
declare -A touched=()

while IFS= read -r line || [ -n "$line" ]; do
  trimmed="$(trim "$line")"
  if [[ "$trimmed" == *"="* ]]; then
    parsed_key="${trimmed%%=*}"
    parsed_key="$(trim "$parsed_key")"
    if [ -n "${final_values[$parsed_key]+x}" ]; then
      if [ -z "${touched[$parsed_key]+x}" ]; then
        printf '%s=%s\n' "$parsed_key" "${final_values[$parsed_key]}" >> "$tmp_env"
        touched["$parsed_key"]=1
      fi
      # Drop duplicate managed-key lines from existing .env so first normalized value wins.
      continue
    fi
  fi
  printf '%s\n' "$line" >> "$tmp_env"
done < "$input_file"

managed_keys=(
  "APP_PORT"
  "PGHOST"
  "PGPORT"
  "MAILPIT__PORT"
  "MAILPIT__SMTP_PORT"
  "COMPOSE_PROJECT_NAME"
  "PGUSER"
  "PGPASSWORD"
  "PGDATABASE"
  "SCHEDULER_TEST_DB_NAME"
  "SESSION__COOKIE_NAME"
  "SESSION__COOKIE_SECURE"
  "SERVER__SERVER_NAME"
  "MAIL__DEFAULT_SENDER"
  "SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS"
  "AUTH_TEST__SHARED_SECRET"
  "MAIL__SERVER"
  "MAIL__PORT"
  "MAIL__SUPPRESS_SEND"
)

for key in "${managed_keys[@]}"; do
  if [ -z "${touched[$key]+x}" ]; then
    printf '%s=%s\n' "$key" "${final_values[$key]}" >> "$tmp_env"
  fi
done

mv "$tmp_env" "$target_env_file"

changed=0
for key in "${managed_keys[@]}"; do
  old="${existing_env[$key]-}"
  new="${final_values[$key]}"
  if [ "$old" != "$new" ]; then
    changed=1
  fi
done

if (( changed )); then
  echo "Updated scoped values in .env"
else
  echo "No managed changes to .env"
fi

echo "  APP_PORT=$app_port PGPORT=$pg_port MAILPIT__PORT=$mailpit_port MAILPIT__SMTP_PORT=$mailpit_smtp_port"
echo "  COMPOSE_PROJECT_NAME=$compose_project"
echo "  SESSION__COOKIE_NAME=$session_cookie_name"
echo "  PGDATABASE=$pg_database"
echo "  SCHEDULER_TEST_DB_NAME=$test_db_name"

if [ "${AUTH_TEST__SHARED_SECRET_GENERATED:-0}" -eq 1 ]; then
  echo "Generated random AUTH_TEST__SHARED_SECRET"
fi
echo "Generated .env from $sample_file for scope=$scope_base"

export RUNTIME_SCOPE_PGHOST="$pg_host"
export RUNTIME_SCOPE_PGPORT="$pg_port"
export RUNTIME_SCOPE_APP_PORT="$app_port"
export RUNTIME_SCOPE_INTEGRATION_APP_PORT="$((app_port + 60))"
export RUNTIME_SCOPE_MAILPIT_APP_PORT="$mailpit_port"
export RUNTIME_SCOPE_MAILPIT_APP_SMTP_PORT="$mailpit_smtp_port"
export RUNTIME_SCOPE_MAILPIT_UNIT_PORT="$((mailpit_port + 20))"
export RUNTIME_SCOPE_MAILPIT_UNIT_SMTP_PORT="$((mailpit_smtp_port + 20))"
export RUNTIME_SCOPE_MAILPIT_ROUTES_PORT="$((mailpit_port + 40))"
export RUNTIME_SCOPE_MAILPIT_ROUTES_SMTP_PORT="$((mailpit_smtp_port + 40))"
export RUNTIME_SCOPE_MAILPIT_INTEGRATION_PORT="$((mailpit_port + 60))"
export RUNTIME_SCOPE_MAILPIT_INTEGRATION_SMTP_PORT="$((mailpit_smtp_port + 60))"
export RUNTIME_SCOPE_COMPOSE_PROJECT_NAME="$compose_project"
export RUNTIME_SCOPE_PGDATABASE="$pg_database"
export RUNTIME_SCOPE_SCHEDULER_TEST_DB_NAME="$test_db_name"
export RUNTIME_SCOPE_SESSION__COOKIE_NAME="$session_cookie_name"
export RUNTIME_SCOPE_AUTH_TEST__SHARED_SECRET="$auth_test_secret"
runtime_scope_write_metadata "$RUNTIME_SCOPE_FILE"

if [ ! -f "$target_env_file" ]; then
  echo "ERROR: expected .env output missing at $target_env_file." >&2
  exit 1
fi
