#!/bin/bash
set -e

# Run database migrations from the migrations directory
cd migrations
alembic upgrade head
cd ..

# Start the application
flask run --host 0.0.0.0 --port 5051
