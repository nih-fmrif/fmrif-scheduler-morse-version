# Scheduler app

## Documentation

For detailed documentation, please refer to:
- [Project Documentation](docs/README.md)
- [Project Summary](summary.md)

## Setup

### Configure the application

The application is configured using .env files (see a more detailed
configuration guide in
[docs/configuration-guide.md](docs/configuration-guide.md)). Run the following
command to get started quickly. Change sensitive values when ready to deploy.

```
bash setup-dotenv.sh
```

## Environment Variables

The application uses PostgreSQL connection parameters that can be configured in two ways:

### Using .env file (recommended for development)
Create a `.env` file in the project root with these variables:
```
PGHOST=localhost
PGPORT=5050
PGUSER=postgres
PGPASSWORD=FMRIF-postgres-123
PGDATABASE=fmrif_scheduler
```

### Using environment variables (recommended for production)
If you prefer to set environment variables directly (which will override .env values):
```bash
export PGHOST=localhost
export PGPORT=5050
export PGUSER=postgres
export PGPASSWORD=FMRIF-postgres-123
export PGDATABASE=fmrif_scheduler
```

### Important Note on PostgreSQL Variables
- Native PostgreSQL tools use `PG*` variables (PGHOST, PGPORT, etc.)
- Docker PostgreSQL images use `POSTGRES_*` variables (POSTGRES_PASSWORD, etc.)

When using Docker, you'll need both sets of variables as shown in the Docker setup below.

## Install/Run the application

With postgres and ldap running independently you can configure and deploy the
application yourself. The python dependencies are specified in pyproject.toml.
They can be installed using most python package managers. uv has many advantages
over pip and is recommended. From project root the following installs uv, and
runs the application:
```
wget -qO- https://astral.sh/uv/install.sh | sh
uv run flask run --host 0.0.0.0 --port 5051
```

## Local development/testing

### Deployment Setup

1. Start PostgreSQL server however you wish, the following could work assuming you are using the correct postgres variables from .env:
```bash
docker run --name postgres_db \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=fmrif_scheduler \
  -p 5444:5432 \
  --rm \
  -v pgdata:/var/lib/postgresql/data \
  postgres:15
```

2. Initialize the database (use DROP_DB=true to reset existing database):
```bash
DROP_DB=true bash sql/000-init.sh
```

3. Run the application:
```bash
uv run flask run --host 0.0.0.0 --port 5051
```

### Docker Setup

Dependencies:
- Podman and Podman Compose

The following will run a containerized postgres database, initialize the
database schema, configure the application to use an example LDAP server,and run
the application:

```
bash run.sh
```

This will start:
- PostgreSQL on port 5050
- LDAP server on port 1389 (not yet used)
- Scheduler application on port 5051


### Backend testing

Tests can be run either with Docker or against a standalone database:

```bash
uv sync --all-extras

# With Docker (recommended for development)
uv run pytest

# With standalone setup (PostgreSQL running on port 5444)
PGHOST=localhost PGPORT=5444 PGDATABASE=scheduler_test pytest
```

### Frontend testing

Dependencies:
- Node.js 18+ (for testing frontend)

1. Install Node.js dependencies:
```bash
npm ci --no-optional
```

1. Install Playwright browsers:
```bash
npx playwright install --with-deps
```

1. Run tests:
```bash
npm run test
```
