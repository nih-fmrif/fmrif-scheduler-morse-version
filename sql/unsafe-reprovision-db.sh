#!/bin/bash

set -e

# Set environment variables for Postgres connection
export PGHOST=127.0.0.1
export PGPORT=5050
export PGUSER=postgres
export PGPASSWORD=postgres
container_name=$(docker ps -q --filter "ancestor=postgres" --format "{{.Names}}")
fatal() {
	echo "$@" 1>&2
	exit 2
}

if ! test -f 003-import-data.sql; then
	fatal "missing 003-import-data.sql (data only dump from original database, not included in repo)"
fi

# these files need to exist but they do not need to contain anything other than the appropriate header
if ! test -f user-dept.csv; then
	cat "usr,dept,pi" >user-dept.csv
fi
if ! test -f dev-dept.csv; then
	cat "dev,dept" >dev-dept.csv
fi
if ! test -f devperm.csv; then
	cat "usr,dev,templates,slot,technologist,medical,training" >devperm.csv
fi

dropdb --if-exists scheduler
createdb scheduler --encoding=UTF-8 --lc-collate=C.UTF-8 --lc-ctype=C.UTF-8 --template=template0

for sql in $(echo "[0-9][0-9][0-9]-*.sql" | sort); do
	echo "=== running: $sql"
	psql -X -q -f "$sql" -d scheduler
done

# docker exec -i "$container_name" pg_dump -s -O --no-acl -d scheduler -U postgres > new-schema.sql

# vacuumdb -f -d scheduler

# ./generate-schemapdf.sh
