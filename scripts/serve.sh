#!/usr/bin/env bash
set -euo pipefail

port="${APP_PORT:-5051}"
export FLASK_APP="${FLASK_APP:-scheduler.app:create_app}"
exec flask run --host 0.0.0.0 --port "$port"
