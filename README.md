
# Scheduler app

## Setup

### Configure the application

The application is configured using .env files (see a more detailed
configuration guide in
[docs/configuration-guide.md](docs/configuration-guide.md)). Run the following
command to get started quickly. Change sensitive values when ready to deploy.

```
bash setup-dotenv.sh
```

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
