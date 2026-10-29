#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF' >&2
Usage: bash scripts/run-debian-runtime-integration.sh <debian-version> [playwright args...]

Examples:
  bash scripts/run-debian-runtime-integration.sh 13.1 --project=chromium tests/playwright/integration/auth-ui.spec.ts
EOF
}

if [ "${1:-}" = "" ]; then
    usage
    exit 1
fi

debian_version=$1
shift

playwright_args=("$@")
if [ "${#playwright_args[@]}" -eq 0 ]; then
    playwright_args=(
        --project=chromium
        --reporter=dot
        --grep-invert=@heavy
    )
fi

export RESET_DEBIAN_RUNTIME_DB=true

bash scripts/with-debian-runtime-stack.sh "$debian_version" -- \
    python3 scripts/run-integration-playwright.py "${playwright_args[@]}"
