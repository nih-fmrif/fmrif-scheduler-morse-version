#!/bin/bash
set -e

# Run database migrations
alembic upgrade head

# Start the application
flask run --host 0.0.0.0 --port 5051
