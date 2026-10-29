#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

args=("$@")

if [[ "${OLD_BOOTSTRAP_SKIP_REBUILD:-}" =~ ^(1|true|yes)$ ]]; then
    args+=(--skip-old-bootstrap)
fi

exec python3 "${PROJECT_ROOT}/scripts/verify-old-bootstrap-compat.py" "${args[@]}"
