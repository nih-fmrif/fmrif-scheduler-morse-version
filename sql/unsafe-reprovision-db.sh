#!/bin/bash

set -e

# Set environment variables for Postgres connection
export PGHOST=127.0.0.1
export PGPORT=5050
export PGUSER=postgres
export PGPASSWORD=postgres

fatal() {
    echo "$@" 1>&2
    exit 2
}

dropdb --if-exists scheduler
createdb scheduler --encoding=UTF-8 --lc-collate=C.UTF-8 --lc-ctype=C.UTF-8 --template=template0

for sql in $(echo "[0-9][0-9][0-9]-*.sql" | sort); do
    echo "=== running: $sql"
    psql -X -q -f "$sql" -d scheduler
done
