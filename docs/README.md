# Scheduler Project Documentation

This documentation provides a comprehensive guide for setting up, developing, and deploying the Scheduler application.

## Table of Contents

1. [Environment Setup](environment-setup.md)
2. [Testing Guide](testing-guide.md)
3. [CI/CD Pipeline](ci-cd-pipeline.md)
4. [Configuration Guide](configuration-guide.md)

# Schema Management

The database schema is managed through SQLAlchemy models and Alembic migrations:

- SQLAlchemy models in `scheduler/models.py` are the source of truth
- Alembic migrations in `scheduler/alembic/` handle live database changes
- SQL files in `sql/` are derived from models for development setup

For production deployments, always use Alembic migrations.