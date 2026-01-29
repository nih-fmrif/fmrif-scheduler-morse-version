
## Configuration Guide

Configuration of the application is done using pydantic-settings (in
[scheduler/config.py](../scheduler/config.py)). This is an approach that makes
use of python types to validate the configuration. It is a powerful, concise,
and flexible approach to organizing configuration. It can be overwritten during
development/deployment using .env files or environment variables.

In order to further organize the configuration we have broken it down into
different classes that are nested in the main configuration class. In python
this is easy to understand and work with; however, it results in a slightly odd
naming patter in the .env files or environment variables when overwriting the
defaults. Each nested class is prepended to the variable name with a double
underscore connection e.g. the "user" that is part of the "database" class can be
overwritten with the environment variable "DATABASE__USER".

Running `setup-dotenv.sh` will create an .env file (from .env.sample.local) in the root of the project
with the default values. This file can be modified to set the desired values for
the environment.
The application fails fast if a required `.env` file is missing.

Note that CI and local development use the root `.env` instantiated from
`.env.sample.local`.

Some useful variables that one might consider setting are listed below.



### Configuration Categories

#### Flask Settings
```env
FLASK_APP=scheduler.app
FLASK_ENV=development
```

#### Server Settings
```env
SERVER__SERVER_NAME=localhost:5051
SERVER__APPLICATION_ROOT=
```

#### Database Settings
```env
PGHOST=postgres
PGPORT=5432
PGUSER=postgres
PGPASSWORD=postgres
PGDATABASE=scheduler
```

#### Authentication Settings
```env
# Entra / OIDC settings
ENTRA__CLIENT_ID=00000000-0000-0000-0000-000000000000
ENTRA__TENANT_ID=00000000-0000-0000-0000-000000000000
ENTRA__DISCOVERY_URL=https://login.microsoftonline.com/${ENTRA__TENANT_ID}/v2.0/.well-known/openid-configuration
ENTRA__REDIRECT_URI=https://fmrif-schedule-backend-staging.nimh.nih.gov
# Optional: additional accepted audiences for JWT validation
# ENTRA__ALLOWED_AUDIENCES=["api://00000000-0000-0000-0000-000000000000"]

## Superuser Mode (local development only)
RBAC__SUPERUSER_MODE=true
```
When `RBAC__SUPERUSER_MODE=false`, Entra settings must be set to non-placeholder values.

#### Mail Settings
```env
MAIL__SERVER=localhost
MAIL__PORT=25
MAIL__USERNAME=test
MAIL__PASSWORD=test
```

### Deployment Specific Configuration

1. **Docker Environment**
   - Uses `.env` automatically and also mounts the .env file into the container
   - Services communicate via Docker network
   - Database host is `postgres`

2. **Deployment/Containerless local development**
   - Uses `.env`
   - Services must be setup/configured independently
