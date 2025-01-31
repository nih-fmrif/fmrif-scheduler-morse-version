#!/bin/bash

# set -e

# Set environment variables for psql connection
# NOTE: always uses port 5050. Check other replacement logic in the sed commands
export $(cat .env | sed 's/^POSTGRES_DB/PGDATABASE/' | sed 's/^POSTGRES_/PG/' | sed 's/^PGPORT=.*/PGPORT=5050/')

fatal() {
    echo "$@" 1>&2
    exit 2
}

dropdb --if-exists $PGDATABASE
createdb $PGDATABASE --encoding=UTF-8 --lc-collate=C.UTF-8 --lc-ctype=C.UTF-8 --template=template0

for sql in $(echo "[0-9][0-9][0-9]-*.sql" | sort); do
    echo "=== running: $sql"
    psql -X -q -f "$sql" -d $PGDATABASE
done
