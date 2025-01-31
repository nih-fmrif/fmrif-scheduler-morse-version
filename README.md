
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

Dependencies:
- Podman and Podman Compose

The following will run a containerized postgres database, initialize the
database schema, configure the application to use an example LDAP server,and run
the application:

```
docker compose up --build
```

This will start:
- PostgreSQL on port 5050
- LDAP server on port 1389 (not yet used)
- Scheduler application on port 5051


### Backend testing

```bash
uv sync --all-extras
uv run pytest
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
