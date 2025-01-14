#!/bin/bash
set -e

# Run database migrations
alembic upgrade head

# Start the application
exec flask run --host 0.0.0.0
