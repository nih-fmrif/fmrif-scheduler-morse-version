#!/usr/bin/env bash
# Database initialization script

# Note: This script requires PostgreSQL connection parameters to be 
# available as environment variables (PGHOST, PGPORT, PGUSER, PGPASSWORD)
# You can set these by either:
# 1. Using your .env file (the application will load it)
# 2. Explicitly exporting variables before running: 
#    export PGHOST=localhost PGPORT=5050 ... then run this script

set -euo pipefail

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

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

    log "Executing $file..."
    # Redirect stderr to stdout to capture all output
    output=$(PGPASSWORD="$PGPASSWORD" psql -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -f "$file" 2>&1)
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

# Verify essential variables are set
essential_vars=("PGUSER" "PGPASSWORD" "PGDATABASE")
missing_vars=()
for var in "${essential_vars[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        missing_vars+=("$var")
    fi
done

if [[ ${#missing_vars[@]} -gt 0 ]]; then
    log "Error: Missing required environment variables: ${missing_vars[*]}"
    exit 1
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

# Attempt to cd into Docker environment (PROJECT_ROOT/sql)
if cd "${PROJECT_ROOT}/sql" 2>/dev/null; then
  echo "Entered container-style directory: ${PROJECT_ROOT}/sql"
# Otherwise, fall back to local setup (SCRIPT_DIR)
else
  echo "Falling back to local directory: ${SCRIPT_DIR}"
  cd "${SCRIPT_DIR}"
fi

# First execute schema file explicitly
if [ -f "001-schema.sql" ]; then
    execute_sql_file "001-schema.sql"
else
    log "WARNING: Base schema file 001-schema.sql not found"
    exit 1
fi

# Then execute all other numbered migration files in order
for sql in $(ls [0-9][0-9][0-9]-*.sql | sort); do
    # Skip schema file as it's already executed
    if [ "$sql" = "001-schema.sql" ]; then
        log "Skipping $sql..."
        continue
    fi

    if [ -f "$sql" ]; then
        execute_sql_file "$sql"
    fi
done

log "All migrations completed successfully"

# Verify database setup
log "Verifying database setup..."
if ! execute_psql "$TARGET_DB" "\dt" > /dev/null 2>&1; then
    log_error "Database verification failed"
    exit 1
fi

log "Database setup completed successfully"
