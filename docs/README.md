# Scheduler Project Documentation

## Core docs
1. [Configuration Guide](configuration-guide.md)
2. [Testing Guide](testing-guide.md)
3. [Testing Strategy](testing-strategy.md)
4. [Containerized PostgreSQL Guide](containerized-postgres.md)
5. [Security Guide](security.md)
6. [UX Guidelines](ux-guidelines.md)
7. [CSS Style Ownership](css-style-ownership.md)

## Agent guidance
1. [Agent Guidance: Quickstart](agent-guidance-quickstart.md)
2. [Agent Guidance: Isolation Validation](agent-guidance-isolation-validation.md)
3. [Agent Guidance: Playwright](agent-guidance-playwright.md)

# Schema Management

The database schema is managed through SQLAlchemy models and Alembic migrations:

- SQLAlchemy models in `scheduler/model.py` are the source of truth
- Alembic migrations in `scheduler/alembic/` handle live database changes
- SQL files in `sql/` are derived from models for development setup

For production deployments, always use Alembic migrations.

## Alembic Details

1. To apply migrations to a database (e.g., production or development), run:
   ```
   alembic upgrade head
   ```
   This will bring your database schema up to the latest revision.
