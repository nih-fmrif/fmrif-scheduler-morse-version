#!/usr/bin/env bash
set -euo pipefail

sample_file=".env.sample.local"
secret_placeholder="__GENERATE_AUTH_TEST_SECRET__"

if [ ! -f "$sample_file" ]; then
  echo "ERROR: $sample_file was not found. Create it or copy from the template." >&2
  exit 1
fi

sanitize_scope() {
  local raw_scope=$1
  local scope

  raw_scope="${raw_scope#\#}"
  scope="$(printf '%s' "$raw_scope" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_' '-')"
  scope="${scope#-}"
  scope="${scope%-}"
  scope="$(printf '%s' "$scope" | sed -E 's/--+/-/g')"
  printf '%s' "${scope:-local}"
}

short_hash8() {
  local raw=$1
  local hash
  hash="$(printf '%s' "$raw" | cksum | awk '{print $1}')"
  printf '%08x' $((hash % 2147483647))
}

validate_port() {
  local port=$1
  local name=$2

  if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    echo "ERROR: $name must be numeric and between 1 and 65535: $port" >&2
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

port_in_list() {
  local needle=$1
  shift || true
  local candidate
  for candidate in "$@"; do
    if [ -n "$candidate" ] && [ "$candidate" = "$needle" ]; then
      return 0
    fi
  done
  return 1
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
    echo "ERROR: Cannot test port usage without lsof, ss, netstat, or python3." >&2
    exit 1
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

pick_available_port() {
  local preferred=$1
  local label=$2
  shift 2 || true
  local excluded=("$@")
  local candidate
  local attempts=0
  local scan

  validate_port "$preferred" "$label preferred port"

  if ! port_in_list "$preferred" "${excluded[@]}" && ! port_is_in_use "$preferred"; then
    printf '%s' "$preferred"
    return 0
  fi

  while (( attempts < 256 )); do
    candidate=$(( (RANDOM * 32768 + RANDOM) % 45536 + 20000 ))
    if port_in_list "$candidate" "${excluded[@]}"; then
      attempts=$((attempts + 1))
      continue
    fi
    if ! port_is_in_use "$candidate"; then
      printf '%s' "$candidate"
      return 0
    fi
    attempts=$((attempts + 1))
  done

  for (( scan = 20000; scan <= 65535; scan += 1 )); do
    if port_in_list "$scan" "${excluded[@]}"; then
      continue
    fi
    if ! port_is_in_use "$scan"; then
      printf '%s' "$scan"
      return 0
    fi
  done

  echo "ERROR: no available port found for $label" >&2
  exit 1
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

if [ -n "${WORKTREE_SCOPE:-}" ]; then
  echo "WARN: ignoring WORKTREE_SCOPE override; setup-dotenv.sh always derives scope from worktree path." >&2
fi
worktree_scope="$(sanitize_scope "${PWD##*/}-wt-$(short_hash8 "$PWD")")"
if [ -n "${APP_PORT:-}" ]; then
  app_port="${APP_PORT}"
  validate_port "$app_port" "APP_PORT"
  if port_is_in_use "$app_port"; then
    echo "ERROR: APP_PORT=$app_port is already in use. Unset APP_PORT to auto-pick a free port." >&2
    exit 1
  fi
else
  app_port="$(pick_available_port 5051 "APP_PORT")"
fi

if [ -n "${PGPORT:-}" ]; then
  pg_port="${PGPORT}"
  validate_port "$pg_port" "PGPORT"
  if [ "$pg_port" = "$app_port" ]; then
    echo "ERROR: PGPORT must differ from APP_PORT ($app_port)." >&2
    exit 1
  fi
  if port_is_in_use "$pg_port"; then
    echo "ERROR: PGPORT=$pg_port is already in use. Unset PGPORT to auto-pick a free port." >&2
    exit 1
  fi
else
  pg_port="$(pick_available_port 5444 "PGPORT" "$app_port")"
fi

if [ -n "${MAILPIT__PORT:-}" ]; then
  mailpit_port="${MAILPIT__PORT}"
  validate_port "$mailpit_port" "MAILPIT__PORT"
  if [ "$mailpit_port" = "$app_port" ] || [ "$mailpit_port" = "$pg_port" ]; then
    echo "ERROR: MAILPIT__PORT must differ from APP_PORT ($app_port) and PGPORT ($pg_port)." >&2
    exit 1
  fi
  if port_is_in_use "$mailpit_port"; then
    echo "ERROR: MAILPIT__PORT=$mailpit_port is already in use. Unset MAILPIT__PORT to auto-pick a free port." >&2
    exit 1
  fi
else
  mailpit_preferred=$((pg_port + 1))
  if (( mailpit_preferred > 65535 )); then
    mailpit_preferred=8025
  fi
  mailpit_port="$(pick_available_port "$mailpit_preferred" "MAILPIT__PORT" "$app_port" "$pg_port")"
fi

if [ -n "${MAILPIT__SMTP_PORT:-}" ]; then
  mailpit_smtp_port="${MAILPIT__SMTP_PORT}"
  validate_port "$mailpit_smtp_port" "MAILPIT__SMTP_PORT"
  if [ "$mailpit_smtp_port" = "$app_port" ] || [ "$mailpit_smtp_port" = "$pg_port" ] || [ "$mailpit_smtp_port" = "$mailpit_port" ]; then
    echo "ERROR: MAILPIT__SMTP_PORT must differ from APP_PORT ($app_port), PGPORT ($pg_port), and MAILPIT__PORT ($mailpit_port)." >&2
    exit 1
  fi
  if port_is_in_use "$mailpit_smtp_port"; then
    echo "ERROR: MAILPIT__SMTP_PORT=$mailpit_smtp_port is already in use. Unset MAILPIT__SMTP_PORT to auto-pick a free port." >&2
    exit 1
  fi
else
  mailpit_smtp_preferred=$((pg_port + 2))
  if (( mailpit_smtp_preferred > 65535 )); then
    mailpit_smtp_preferred=8026
  fi
  mailpit_smtp_port="$(pick_available_port "$mailpit_smtp_preferred" "MAILPIT__SMTP_PORT" "$app_port" "$pg_port" "$mailpit_port")"
fi

compose_project="${COMPOSE_PROJECT_NAME:-scheduler-${worktree_scope}}"
pg_database="${PGDATABASE:-fmrif_scheduler_${worktree_scope}}"
scheduler_test_db="${SCHEDULER_TEST_DB_NAME:-fmrif_scheduler_test_${worktree_scope}}"
session_cookie_name="${SESSION__COOKIE_NAME:-dsid-${worktree_scope}}"
session_cookie_secure="${SESSION__COOKIE_SECURE:-false}"
security_auth_rate_limit_max_requests="${SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS:-120}"
server_name="${SERVER__SERVER_NAME:-}"
mail_default_sender="${MAIL__DEFAULT_SENDER:-scheduler-${worktree_scope}@localhost.localdomain}"

if [[ "$mail_default_sender" != *"@"* ]]; then
  echo "ERROR: MAIL__DEFAULT_SENDER must be an email address: $mail_default_sender" >&2
  exit 1
fi

validate_port "$app_port" "APP_PORT"
validate_port "$pg_port" "PGPORT"
validate_port "$mailpit_port" "MAILPIT__PORT"
validate_port "$mailpit_smtp_port" "MAILPIT__SMTP_PORT"
validate_positive_int \
  "$security_auth_rate_limit_max_requests" \
  "SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS"

auth_test_secret="$(generate_secret)"

tmp_env="$(mktemp)"
awk -v placeholder="$secret_placeholder" \
  -v secret="$auth_test_secret" \
  -v app_port="$app_port" \
  -v pg_port="$pg_port" \
  -v mailpit_port="$mailpit_port" \
  -v mailpit_smtp_port="$mailpit_smtp_port" \
  -v compose_project="$compose_project" \
  -v pg_database="$pg_database" \
  -v scheduler_test_db="$scheduler_test_db" \
  -v session_cookie_name="$session_cookie_name" \
  -v session_cookie_secure="$session_cookie_secure" \
  -v security_auth_rate_limit_max_requests="$security_auth_rate_limit_max_requests" \
  -v server_name="$server_name" \
  -v mail_default_sender="$mail_default_sender" \
  '
  {
    if ($0 ~ /^APP_PORT=/) {
      print "APP_PORT=" app_port
      next
    }
    if ($0 ~ /^PGPORT=/) {
      print "PGPORT=" pg_port
      next
    }
    if ($0 ~ /^MAILPIT__PORT=/) {
      print "MAILPIT__PORT=" mailpit_port
      next
    }
    if ($0 ~ /^MAILPIT__SMTP_PORT=/) {
      print "MAILPIT__SMTP_PORT=" mailpit_smtp_port
      next
    }
    if ($0 ~ /^COMPOSE_PROJECT_NAME=/) {
      print "COMPOSE_PROJECT_NAME=" compose_project
      next
    }
    if ($0 ~ /^PGDATABASE=/) {
      print "PGDATABASE=" pg_database
      next
    }
    if ($0 ~ /^SCHEDULER_TEST_DB_NAME=/) {
      print "SCHEDULER_TEST_DB_NAME=" scheduler_test_db
      next
    }
    if ($0 ~ /^SESSION__COOKIE_NAME=/) {
      print "SESSION__COOKIE_NAME=" session_cookie_name
      next
    }
    if ($0 ~ /^SESSION__COOKIE_SECURE=/) {
      print "SESSION__COOKIE_SECURE=" session_cookie_secure
      next
    }
    if ($0 ~ /^SERVER__SERVER_NAME=/) {
      print "SERVER__SERVER_NAME=" server_name
      next
    }
    if ($0 ~ /^SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS=/) {
      print "SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS=" security_auth_rate_limit_max_requests
      next
    }
    if ($0 ~ /^MAIL__PORT=/) {
      print "MAIL__PORT=" mailpit_smtp_port
      next
    }
    if ($0 ~ /^MAIL__DEFAULT_SENDER=/) {
      print "MAIL__DEFAULT_SENDER=" mail_default_sender
      next
    }
    if ($0 ~ /^AUTH_TEST__SHARED_SECRET=/ && index($0, placeholder) > 0) {
      print "AUTH_TEST__SHARED_SECRET=" secret
      next
    }
    print
  }
' "$sample_file" > "$tmp_env"

cp "$tmp_env" .env
rm -f "$tmp_env"

echo "Generated .env from $sample_file for scope=$worktree_scope"
echo "  APP_PORT=$app_port PGPORT=$pg_port MAILPIT__PORT=$mailpit_port MAILPIT__SMTP_PORT=$mailpit_smtp_port"
echo "  COMPOSE_PROJECT_NAME=$compose_project"
echo "  SESSION__COOKIE_NAME=$session_cookie_name"
echo "  SESSION__COOKIE_SECURE=$session_cookie_secure"
echo "  SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS=$security_auth_rate_limit_max_requests"
echo "Host app command: APP_PORT=$app_port pixi run serve"
echo "Generated random AUTH_TEST__SHARED_SECRET"
