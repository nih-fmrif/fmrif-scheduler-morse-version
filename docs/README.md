# Scheduler Project Documentation

This documentation provides a comprehensive guide for setting up, developing, and deploying the Scheduler application.

## Table of Contents

1. [Configuration Guide](configuration-guide.md)
2. [Testing Guide](testing-guide.md)

# Schema Management

The database schema is managed through SQLAlchemy models and Alembic migrations:

- SQLAlchemy models in `scheduler/models.py` are the source of truth
- Alembic migrations in `scheduler/alembic/` handle live database changes
- SQL files in `sql/` are derived from models for development setup

For production deployments, always use Alembic migrations.

## Alembic Details    

1. To apply migrations to a database (e.g., production or development), run:
   ```
   alembic upgrade head
   ```
   This will bring your database schema up to the latest revision.