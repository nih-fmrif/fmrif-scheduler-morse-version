
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

Note that CI and local development use the .env.docker files instantiated from
.env.sample files. These can be ignored unless you are working on the CI/CD
pipeline.

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
DATABASE__HOST=postgres
DATABASE__PORT=5432
DATABASE__USER=postgres
DATABASE__PASSWORD=postgres
DATABASE__DB=scheduler
```

#### Authentication Settings
```env
## LDAP Settings (when not in superuser mode)
LDAP__HOST=ldap
LDAP__PORT=389
LDAP__USE_SSL=false
LDAP__BIND_DN=cn=read-only-admin,dc=example,dc=com

## Superuser Mode
RBAC__SUPERUSER_MODE=true
```

#### Mail Settings
```env
MAIL__SERVER=localhost
MAIL__PORT=25
MAIL__USERNAME=test
MAIL__PASSWORD=test
```

### Deployment Specific Configuration

1. **Docker Environment**
   - Uses `.env.docker`
   - Services communicate via Docker network
   - Database host is `postgres`

2. **Deployment/Containerless local development**
   - Uses `.env`
   - Services must be setup/configured independently
