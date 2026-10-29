#!/usr/bin/env bash
# Database initialization script

# Note: This script requires PostgreSQL connection parameters to be
# available as environment variables (PGHOST, PGPORT, PGUSER, PGPASSWORD)
# You can set these by either:
# 1. Using your .env file (the application will load it)
# 2. Explicitly exporting variables before running:
#    export PGHOST=localhost PGPORT=5444 ... then run this script

set -euo pipefail

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SCRIPT_DIR_ABS="$( cd "$SCRIPT_DIR" && pwd )"

# Function to log messages with timestamp
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

# Function to log errors in red
log_error() {
    echo -e "\033[0;31m[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1\033[0m"
}

# Function to handle schema conflicts with helpful message
handle_schema_conflict() {
    local error_msg="$1"
    local file="$2"
    local sql_error="$3"

    echo
    log_error "Schema conflict in $file"
    echo
    echo "SQL Error:"
    echo "----------------------------------------"
    echo "$sql_error"
    echo "----------------------------------------"
    echo
    echo "This error typically means that some database objects already exist."
    echo "This can happen if:"
    echo "  1. You've run the migrations before"
    echo "  2. You have a partially migrated database"
    echo "  3. There are leftover objects from a previous installation"
    echo
    echo "To fix this, you can:"
    echo "  1. Drop and recreate the database with:"
    echo "     DROP_DB=true bash $0"
    echo
    echo "  2. If you need to preserve data, you'll need to manually resolve the conflicts"
    echo "     by examining the SQL error above and the migration file: $file"
    echo
    exit 1
}

# Function to check if postgres is accepting connections
check_postgres() {
    local retries=5
    local wait_time=5

    log "Checking PostgreSQL connection..."
    while [ $retries -gt 0 ]; do
        export PGUSER="$PGUSER"
        export PGPASSWORD="$PGPASSWORD"
        export PGDATABASE="$PGDATABASE"
        if pg_isready; then
            log "PostgreSQL is accepting connections"
            return 0
        fi
        retries=$((retries-1))
        if [ $retries -gt 0 ]; then
            log "PostgreSQL not ready, waiting ${wait_time}s... ($retries attempts left)"
            sleep $wait_time
        fi
    done
    log_error "Could not connect to PostgreSQL after multiple attempts"
    return 1
}

# Function to safely execute psql commands
execute_psql() {
    local db=$1
    local command=$2
    PGPASSWORD="$PGPASSWORD" psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$db" -c "$command" 2>&1
}

# Function to safely execute psql files with error handling
execute_sql_file() {
    local file=$1
    local output

    local user_dept_csv=${SQL_USER_DEPT_CSV:-}
    local dev_dept_csv=${SQL_DEV_DEPT_CSV:-}
    local devperm_csv=${SQL_DEVPERM_CSV:-}
    local psql_cmd=(
        psql
        -v ON_ERROR_STOP=1
        -U "$PGUSER"
        -d "$PGDATABASE"
        -v "USER_DEPT_CSV=${user_dept_csv}"
        -v "DEV_DEPT_CSV=${dev_dept_csv}"
        -v "DEVPERM_CSV=${devperm_csv}"
    )

    log "Executing $file..."
    # Load the canonical seed dump with FK/trigger checks relaxed because
    # data-only dumps rely on this when loading into an already-constrained schema.
    if [ "${file}" = "${SEED_DUMP_FILE}" ]; then
        output=$(PGPASSWORD="$PGPASSWORD" "${psql_cmd[@]}" <<SQL 2>&1
SET session_replication_role = replica;
\i '${file}'
SET session_replication_role = DEFAULT;
SQL
        )
    else
        # Redirect stderr to stdout to capture all output
        output=$(PGPASSWORD="$PGPASSWORD" "${psql_cmd[@]}" -f "$file" 2>&1)
    fi
    local status=$?

    if [ $status -ne 0 ]; then
        # Check for common schema conflict errors
        if echo "$output" | grep -q "relation.*already exists" || \
           echo "$output" | grep -q "duplicate key value violates unique constraint" || \
           echo "$output" | grep -q "current database is not empty"; then
            handle_schema_conflict "Failed to execute $file" "$file" "$output"
        else
            log_error "Failed to execute $file"
            echo
            echo "Error output:"
            echo "----------------------------------------"
            echo "$output"
            echo "----------------------------------------"
            exit 1
        fi
    fi

    # Only output if it's not empty
    if [ -n "$output" ]; then
        echo "$output"
    fi
    return 0
}

# Validate that every COPY data row has the same field count as its COPY header.
# This catches accidental delimiter corruption in large seed dumps early.
validate_seed_dump_copy_shape() {
    local dump_file=$1
    local max_samples=20
    local report

    report="$(awk -v max_samples="$max_samples" '
BEGIN {
  FS="\t"
  in_copy=0
  expected=0
  table=""
  total=0
  samples=0
}
/^COPY / {
  in_copy=1
  line=$0
  sub(/^COPY[ ]+/, "", line)
  table=line
  sub(/[ ]*\(.*/, "", table)

  cols=$0
  sub(/^COPY [^\(]*\(/, "", cols)
  sub(/\) FROM stdin;.*/, "", cols)
  gsub(/[^,]/, "", cols)
  expected=length(cols)+1
  next
}
in_copy && $0 == "\\." {
  in_copy=0
  expected=0
  table=""
  next
}
in_copy {
  got=NF
  if (got != expected) {
    total++
    if (samples < max_samples) {
      samples++
      print NR "|" table "|expected=" expected "|got=" got
    }
  }
}
END {
  print "TOTAL_MISMATCHES=" total
}
' "$dump_file")" || {
        log_error "Failed to validate COPY row shape in $dump_file"
        exit 1
    }

    local mismatch_total
    mismatch_total="$(echo "$report" | awk -F= '/^TOTAL_MISMATCHES=/{print $2}')"

    if [ "${mismatch_total:-0}" -gt 0 ]; then
        log_error "Seed dump has malformed COPY rows (${mismatch_total} mismatches): $dump_file"
        echo "$report" | grep -v '^TOTAL_MISMATCHES='
        echo "Fix the seed dump tab-delimited row shape and retry."
        exit 1
    fi

    log "Seed dump COPY row shape validated: $dump_file"
}

# Verify essential variables are set
essential_vars=("PGUSER" "PGPASSWORD" "PGDATABASE")
missing_vars=()
for var in "${essential_vars[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        missing_vars+=("$var")
    fi
done

# Support both default and custom seed file locations.
if [ -z "${SQL_SEED_DUMP_FILE:-}" ] || [ -z "${SQL_USER_DEPT_CSV:-}" ] || [ -z "${SQL_DEV_DEPT_CSV:-}" ] || [ -z "${SQL_DEVPERM_CSV:-}" ]; then
  # Support both local execution and container init contexts.
  SQL_DIR_CANDIDATES=(
    "/sql"
    "${SCRIPT_DIR_ABS}"
    "${SCRIPT_DIR_ABS}/.."
    "${SCRIPT_DIR_ABS}/../sql"
  )
  SQL_DIR=""
  for candidate in "${SQL_DIR_CANDIDATES[@]}"; do
    if [ -d "$candidate" ] && [ -f "$candidate/001-schema.sql" ] && [ -f "$candidate/003-import-data.sql" ]; then
      SQL_DIR="$candidate"
      break
    fi
  done

  if [ -z "${SQL_DIR}" ]; then
    cat <<EOF >&2
Missing required SQL root. Checked:
$(printf '  - %s\n' "${SQL_DIR_CANDIDATES[@]}")
Please set SQL_SEED_DUMP_FILE, SQL_USER_DEPT_CSV, SQL_DEV_DEPT_CSV, SQL_DEVPERM_CSV
or ensure the expected SQL files are mounted in /sql or the script directory.
EOF
    exit 1
  fi

  log "Using SQL directory: ${SQL_DIR}"

  SEED_DUMP_FILE=${SQL_SEED_DUMP_FILE:-"$SQL_DIR/003-import-data.sql"}
  SQL_USER_DEPT_CSV=${SQL_USER_DEPT_CSV:-"$SQL_DIR/user-dept.csv"}
  SQL_DEV_DEPT_CSV=${SQL_DEV_DEPT_CSV:-"$SQL_DIR/dev-dept.csv"}
  SQL_DEVPERM_CSV=${SQL_DEVPERM_CSV:-"$SQL_DIR/devperm.csv"}
else
  # Preserve custom explicit paths.
  SEED_DUMP_FILE="$SQL_SEED_DUMP_FILE"
  SQL_USER_DEPT_CSV="$SQL_USER_DEPT_CSV"
  SQL_DEV_DEPT_CSV="$SQL_DEV_DEPT_CSV"
  SQL_DEVPERM_CSV="$SQL_DEVPERM_CSV"
  SQL_DIR="${SCRIPT_DIR_ABS}"
  log "Using custom seed paths from environment variables"
fi

for seed_file in "$SEED_DUMP_FILE" "$SQL_USER_DEPT_CSV" "$SQL_DEV_DEPT_CSV" "$SQL_DEVPERM_CSV"; do
    if [ ! -f "$seed_file" ]; then
        log_error "Missing required seed file: $seed_file"
        exit 1
    fi
done

if [[ ${#missing_vars[@]} -gt 0 ]]; then
    log "Error: Missing required environment variables: ${missing_vars[*]}"
    exit 1
fi

if [ "${SQL_VALIDATE_SEED_DUMP:-true}" = "true" ]; then
    validate_seed_dump_copy_shape "$SEED_DUMP_FILE"
else
    log "Skipping seed dump COPY row shape validation (SQL_VALIDATE_SEED_DUMP=false)"
fi

log "Database connection settings:"
log "Host: (using local Unix socket)"
# log "Port: $POSTGRES_PORT"
log "Database: $PGDATABASE"
log "User: $PGUSER"
log "Password: ********"

# Check if PostgreSQL is accepting connections
if ! check_postgres; then
    log "ERROR: PostgreSQL is not accessible"
    exit 1
fi

# Store target database name
TARGET_DB="${PGDATABASE:-fmrif_scheduler}"
echo "Target database will be: $TARGET_DB"

# First connect to postgres database for admin operations
# This is required as we cannot drop/create the database while connected to it
export PGDATABASE="postgres"

# Drop database if requested
if [ "${DROP_DB:-false}" = "true" ]; then
    log "Attempting to drop database $TARGET_DB..."

    # First, terminate existing connections
    execute_psql "postgres" "
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = '$TARGET_DB'
        AND pid <> pg_backend_pid();" || true

    # Then drop the database
    execute_psql "postgres" "DROP DATABASE IF EXISTS $TARGET_DB;"
fi

# Check if database exists
log "Checking if database $TARGET_DB exists..."
DB_EXISTS=$(execute_psql "postgres" "SELECT 1 FROM pg_database WHERE datname = '$TARGET_DB'" | grep -c "1" || true)

# Create database if it doesn't exist
if [ "$DB_EXISTS" = "0" ]; then
    log "Creating database $TARGET_DB..."
    execute_psql "postgres" "CREATE DATABASE $TARGET_DB
        WITH ENCODING='UTF8'
        LC_COLLATE='C.UTF-8'
        LC_CTYPE='C.UTF-8'
        TEMPLATE=template0;"
else
    log "Database $TARGET_DB already exists"
    echo
    echo "NOTE: If you want to start with a fresh database, you can run:"
    echo "    DROP_DB=true bash $0"
    echo
    echo "This will drop the existing database and recreate it from scratch."
    echo "Only do this if you're sure you want to lose all existing data."
    echo
fi

# Switch back to target database for migrations
export PGDATABASE="$TARGET_DB"
echo "Switched to target database: $PGDATABASE"

# Attempt to operate in the resolved SQL directory.
if cd "${SQL_DIR}" 2>/dev/null; then
  echo "Using SQL directory: ${SQL_DIR}"
else
  echo "Falling back to local directory: ${SCRIPT_DIR_ABS}"
  cd "${SCRIPT_DIR_ABS}"
fi

# First execute schema file explicitly
if [ -f "001-schema.sql" ]; then
    execute_sql_file "001-schema.sql"
else
    log "WARNING: Base schema file 001-schema.sql not found"
    exit 1
fi

# Then execute the snapshot data import SQL dump (or replacement from environment)
if [ -f "$SEED_DUMP_FILE" ]; then
    execute_sql_file "$SEED_DUMP_FILE"
fi

# Then execute all remaining numbered migration files in order
for sql in $(ls [0-9][0-9][0-9]-*.sql | sort); do
    # Skip schema and seed files because base schema is already explicit and
    # seed dump is applied above from a configurable source.
    if [ "$sql" = "001-schema.sql" ] || [ "$sql" = "003-import-data.sql" ] || [ "$sql" = "900-import-new-data.sql" ]; then
        log "Skipping $sql..."
        continue
    fi

    if [ -f "$sql" ]; then
        execute_sql_file "$sql"
    fi
done

# Default relationship hydration import for CSV mappings:
# hydrate auth and relationship tables after the base schema and snapshot import.
if [ -z "${SQL_ADDITIVE_LAYER_FILES+x}" ]; then
    default_mapping_layer="${SQL_DIR}/900-import-new-data.sql"
    if [ -f "$default_mapping_layer" ]; then
        SQL_ADDITIVE_LAYER_FILES="$default_mapping_layer"
    fi
fi

# Optional relationship hydration scripts run after core schema/data migration.
if [ -n "${SQL_ADDITIVE_LAYER_FILES:-}" ]; then
    log "Running additive data layers: ${SQL_ADDITIVE_LAYER_FILES}"
    OLDIFS="$IFS"
    IFS=','
    read -r -a additive_layers <<< "${SQL_ADDITIVE_LAYER_FILES}"
    IFS="$OLDIFS"
    for layer in "${additive_layers[@]}"; do
        layer="$(echo "$layer" | xargs)"
        if [ -z "$layer" ]; then
            continue
        fi
        if [ ! -f "$layer" ]; then
            log_error "Additive layer not found: $layer"
            exit 1
        fi
        execute_sql_file "$layer"
    done
else
    log "No additive data layers configured (set SQL_ADDITIVE_LAYER_FILES to run any)."
fi

log "All migrations completed successfully"

# Verify database setup
log "Verifying database setup..."
if ! execute_psql "$TARGET_DB" "\dt" > /dev/null 2>&1; then
    log_error "Database verification failed"
    exit 1
fi

log "Database setup completed successfully"
