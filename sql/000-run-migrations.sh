#!/bin/bash
set -e

cd /sql

# Skip these files as they contain duplicate/conflicting schemas
SKIP_FILES=(
  "new-schema.sql"
  "scanner_schedule_schema.sql"
  "001-schema.sql"  # This will be executed explicitly first
)

# First execute schema file explicitly
if [ -f "001-schema.sql" ]; then
  echo "Executing base schema (001-schema.sql)..."
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "001-schema.sql"
fi

# Then execute all other numbered migration files in order
for sql in $(ls [0-9][0-9][0-9]-*.sql | sort); do
  # Skip files in SKIP_FILES array
  skip=false
  for skip_file in "${SKIP_FILES[@]}"; do
    if [ "$sql" = "$skip_file" ]; then
      skip=true
      break
    fi
  done

  if [ "$skip" = true ]; then
    echo "Skipping $sql..."
    continue
  fi

  if [ -f "$sql" ]; then
    echo "Executing $sql..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$sql"
  else
    echo "Warning: $sql not found, skipping..."
  fi
done
