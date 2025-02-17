#!/bin/bash
set -e
# override db host and port when in container no matter what (.env gets
# overwritten by env variables)
export PGPORT=5432
export PGHOST=postgres

>&2 echo "Postgres is up - starting application"
# Run database migrations
alembic upgrade head
# Start the application
flask run --host 0.0.0.0 --port 5051
