#!/bin/bash
set -e

cd /sql

# Try to create database if it doesn't exist
psql -v ON_ERROR_STOP=0 <<-EOSQL
    CREATE DATABASE scheduler
    WITH ENCODING='UTF-8'
    LC_COLLATE='C.UTF-8'
    LC_CTYPE='C.UTF-8'
    TEMPLATE=template0;
EOSQL

# Connect to scheduler database for remaining operations
export PGDATABASE=scheduler

# First execute schema file explicitly
if [ -f "001-schema.sql" ]; then
  echo "Executing base schema (001-schema.sql)..."
  psql -v ON_ERROR_STOP=1 -f "001-schema.sql"
fi

# Then execute all other numbered migration files in order
for sql in $(ls [0-9][0-9][0-9]-*.sql | sort); do
  # Skip schema file as it's already executed
  if [ "$sql" = "001-schema.sql" ]; then
    echo "Skipping $sql..."
    continue
  fi

  if [ -f "$sql" ]; then
    echo "Executing $sql..."
    psql -v ON_ERROR_STOP=1 -f "$sql"
  fi
done
