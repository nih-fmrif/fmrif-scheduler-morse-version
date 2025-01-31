#!/bin/bash
set -e

# Wait for database to be ready
until PGPASSWORD=$DATABASE__PASSWORD psql -h "$DATABASE__HOST" -U "$DATABASE__USER" -d "$DATABASE__DB" -c '\q'; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 1
done

>&2 echo "Postgres is up - starting application"
# Run database migrations
alembic upgrade head
# Start the application
flask run --host 0.0.0.0 --port 5051
