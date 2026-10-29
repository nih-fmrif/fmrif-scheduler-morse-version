#!/usr/bin/env bash
set -euo pipefail

port="${APP_PORT:-5051}"
exec flask run --host 0.0.0.0 --port "$port"
