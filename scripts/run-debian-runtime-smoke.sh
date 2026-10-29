#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF' >&2
Usage: bash scripts/run-debian-runtime-smoke.sh <debian-version>

Examples:
  bash scripts/run-debian-runtime-smoke.sh 12.13
  APP_PORT=5082 PGPORT=5542 MAILPIT__PORT=5583 MAILPIT__SMTP_PORT=5584 \
    bash scripts/run-debian-runtime-smoke.sh 13.1
EOF
}

if [ "${1:-}" = "" ]; then
    usage
    exit 1
fi

debian_version=$1

bash scripts/with-debian-runtime-stack.sh "$debian_version" -- \
    bash -lc 'curl -fsS "${TEST_BASE_URL}/auth/login" >/dev/null && echo "Debian runtime smoke passed for ${DEBIAN_VERSION} at ${TEST_BASE_URL}"'
