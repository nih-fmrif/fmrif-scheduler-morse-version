#!/usr/bin/env bash
set -euo pipefail

pattern='^\s*from\s+scheduler\.app\s+import\s+.*\bapp\b'

if rg -n --glob 'tests/unit/test_*.py' "$pattern" tests/unit; then
    cat <<'EOF'
Do not import the global Flask app directly in unit tests.
Use fixture-backed access instead (e.g. route_app, route_client, route_app_context).
EOF
    exit 1
fi
