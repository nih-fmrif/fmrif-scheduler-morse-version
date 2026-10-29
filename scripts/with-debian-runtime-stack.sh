#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF' >&2
Usage: bash scripts/with-debian-runtime-stack.sh <debian-version> -- <command...>

Examples:
  bash scripts/with-debian-runtime-stack.sh 12.13 -- curl -fsS "$TEST_BASE_URL/auth/login"
  bash scripts/with-debian-runtime-stack.sh 13.1 -- python3 scripts/run-integration-playwright.py --project=chromium
EOF
}

if [ "${1:-}" = "" ]; then
    usage
    exit 1
fi

debian_version=$1
shift

if [ "${1:-}" != "--" ]; then
    usage
    exit 1
fi
shift

if [ "$#" -eq 0 ]; then
    usage
    exit 1
fi

set_default_ports() {
    case "$debian_version" in
        12.13)
            export APP_PORT="${APP_PORT:-5081}"
            export PGPORT="${PGPORT:-5541}"
            export MAILPIT__PORT="${MAILPIT__PORT:-5581}"
            export MAILPIT__SMTP_PORT="${MAILPIT__SMTP_PORT:-5582}"
            ;;
        13.1)
            export APP_PORT="${APP_PORT:-5082}"
            export PGPORT="${PGPORT:-5542}"
            export MAILPIT__PORT="${MAILPIT__PORT:-5583}"
            export MAILPIT__SMTP_PORT="${MAILPIT__SMTP_PORT:-5584}"
            ;;
        *)
            export APP_PORT="${APP_PORT:-5051}"
            export PGPORT="${PGPORT:-5444}"
            export MAILPIT__PORT="${MAILPIT__PORT:-5445}"
            export MAILPIT__SMTP_PORT="${MAILPIT__SMTP_PORT:-5446}"
            ;;
    esac
}

set_default_ports

export DEBIAN_VERSION="$debian_version"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-scheduler-debian-runtime-${DEBIAN_VERSION//./-}}"
export AUTH_TEST__ENABLED="${AUTH_TEST__ENABLED:-true}"
export AUTH_TEST__SHARED_SECRET="${AUTH_TEST__SHARED_SECRET:-ci-shared-secret}"
export PLAYWRIGHT_AUTH_MODE="${PLAYWRIGHT_AUTH_MODE:-mock}"
export PLAYWRIGHT_EXTERNAL_SERVER="${PLAYWRIGHT_EXTERNAL_SERVER:-true}"
export RESET_DEBIAN_RUNTIME_DB="${RESET_DEBIAN_RUNTIME_DB:-false}"
export PGDATABASE="${PGDATABASE:-fmrif_scheduler_debian_${DEBIAN_VERSION//./_}}"
export TEST_BASE_URL="${TEST_BASE_URL:-http://127.0.0.1:${APP_PORT}}"
export PLAYWRIGHT_MAILPIT_API_BASE_URL="${PLAYWRIGHT_MAILPIT_API_BASE_URL:-http://127.0.0.1:${MAILPIT__PORT}}"

base_compose_file_path="${BASE_COMPOSE_FILE_PATH:-compose.yaml}"
override_compose_file_path="${OVERRIDE_COMPOSE_FILE_PATH:-compose.debian-runtime.yaml}"
compose_args=(
    -f "$base_compose_file_path"
    -f "$override_compose_file_path"
)

runtime_env_file=""
runtime_env_dir=""

cleanup() {
    local status=$?
    if [ $status -ne 0 ]; then
        docker compose "${compose_args[@]}" logs --no-color || true
    fi
    docker compose "${compose_args[@]}" down --volumes --remove-orphans || true
    if [ -n "$runtime_env_file" ] && [ -f "$runtime_env_file" ]; then
        rm -f "$runtime_env_file"
    fi
    if [ -n "$runtime_env_dir" ]; then
        rmdir "$runtime_env_dir"
    fi
    exit $status
}

trap cleanup EXIT

if [ ! -f .env ]; then
    bash setup-dotenv.sh
fi

runtime_env_dir="$(mktemp -d "${TMPDIR:-/tmp}/scheduler-debian-runtime-env.XXXXXX")"
runtime_env_file="${runtime_env_dir}/.env"
cp .env "$runtime_env_file"
# The private parent directory protects the host copy. The non-root container
# user must be able to read the file mounted into /app/.env.
chmod 0644 "$runtime_env_file"
{
    echo "AUTH_TEST__ENABLED=${AUTH_TEST__ENABLED}"
    echo "AUTH_TEST__SHARED_SECRET=${AUTH_TEST__SHARED_SECRET}"
    echo "PGDATABASE=${PGDATABASE}"
} >> "$runtime_env_file"

export SCHEDULER_COMPOSE_ENV_FILE="$runtime_env_file"
export SCHEDULER_RUNTIME_ENV_FILE="$runtime_env_file"

docker compose "${compose_args[@]}" up --build -d --wait postgres mailpit_app

if [ "$RESET_DEBIAN_RUNTIME_DB" = "true" ]; then
    docker compose "${compose_args[@]}" exec -T postgres \
        bash -lc 'export DROP_DB=true; bash /sql/000-init.sh'
fi

docker compose "${compose_args[@]}" up --build -d --wait scheduler nginx

for attempt in $(seq 1 30); do
    if curl -fsS "${TEST_BASE_URL}/auth/login" >/dev/null; then
        "$@"
        exit $?
    fi
    sleep 2
done

echo "Timed out waiting for ${TEST_BASE_URL}/auth/login" >&2
exit 1
