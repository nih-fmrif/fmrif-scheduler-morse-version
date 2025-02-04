#!/bin/bash

# set -e

# Set environment variables for psql connection
# NOTE: always uses port 5050. Check other replacement logic in the sed commands
export ENVFILE=../.env
while IFS= read -r line; do
    # Skip comments and empty lines
    [[ $line =~ ^#.*$ || -z $line ]] && continue
    # Export the variable
    export "$line"
done < <(cat "$ENVFILE" | grep -v '#' | \
    sed 's/^POSTGRES_DB/PGDATABASE/' | \
    sed 's/^DATABASE__DB/PGDATABASE/' | \
    sed 's/^DATABASE__/PG/' | \
    sed 's/^POSTGRES_/PG/' | \
    sed 's/^PGPORT=.*/PGPORT=5050/' | \
    grep '^PG.*')

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
