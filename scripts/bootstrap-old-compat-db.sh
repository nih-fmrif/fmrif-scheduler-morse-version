#!/usr/bin/env bash
set -euo pipefail

OLD_REPO_ROOT="${1:-$HOME/.codex/worktrees/ade3/fmrif-scheduler-morse-version}"
TARGET_DB="${2:-fmrif_scheduler_oldcompat}"
SQL_DIR="${OLD_REPO_ROOT%/}/sql"

if [ ! -d "$SQL_DIR" ]; then
  echo "Missing old SQL directory: $SQL_DIR" >&2
  exit 1
fi

for required in 003-import-data.sql user-dept.csv dev-dept.csv devperm.csv; do
  if [ ! -f "$SQL_DIR/$required" ]; then
    echo "Missing required old bootstrap input: $SQL_DIR/$required" >&2
    exit 1
  fi
done

: "${PGUSER:?Set PGUSER first}"
: "${PGPASSWORD:?Set PGPASSWORD first}"

dropdb --if-exists "$TARGET_DB"
createdb "$TARGET_DB" --encoding=UTF-8 --lc-collate=C.UTF-8 --lc-ctype=C.UTF-8 --template=template0

for sql in $(cd "$SQL_DIR" && ls [0-9][0-9][0-9]-*.sql | sort); do
  echo "running $sql"
  if [ "$sql" = "001-schema.sql" ]; then
    (
      cd "$SQL_DIR" &&
      sed \
        -e 's/^CREATE PROCEDURAL LANGUAGE plpgsql;$/CREATE EXTENSION IF NOT EXISTS plpgsql;/' \
        -e 's/^create extension plpgsql;$/create extension if not exists plpgsql;/' \
        -e 's/^SET default_with_oids = true;$/SET default_with_oids = false;/' \
        "$sql" |
        psql -X -v ON_ERROR_STOP=1 -f - -d "$TARGET_DB"
    )
  else
    (cd "$SQL_DIR" && psql -X -v ON_ERROR_STOP=1 -f "$sql" -d "$TARGET_DB")
  fi
done

echo "bootstrapped old compatibility database: $TARGET_DB"
