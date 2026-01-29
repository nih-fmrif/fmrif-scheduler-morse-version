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
The application fails fast if a required `.env` file is missing.

## Environment Variables

The application uses PostgreSQL connection parameters that can be configured in two ways:

### Using .env file (recommended for development)
Create a `.env` file in the project root with these variables:
```
PGHOST=localhost
PGPORT=5444
PGUSER=postgres
PGPASSWORD=FMRIF-postgres-123
PGDATABASE=fmrif_scheduler
```

### Using environment variables (recommended for production)
If you prefer to set environment variables directly (which will override .env values):
```bash
export PGHOST=localhost
export PGPORT=5444
export PGUSER=postgres
export PGPASSWORD=FMRIF-postgres-123
export PGDATABASE=fmrif_scheduler
```

### Important Note on PostgreSQL Variables
- Native PostgreSQL tools use `PG*` variables (PGHOST, PGPORT, etc.)
- Docker PostgreSQL images use `POSTGRES_*` variables (POSTGRES_PASSWORD, etc.)

When using Docker, you'll need both sets of variables as shown in the Docker setup below.

## Install/Run the application

With Postgres running independently you can configure and deploy the
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
database schema, and run the application:

```
bash run.sh
```

This will start:
- PostgreSQL on port 5444
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
If you run tests with `RBAC__SUPERUSER_MODE=false`, ensure Entra settings are configured.

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

### Browser-based testing using X11 forwarding on Apple Silicon with XQuartz

When testing browser-based applications via SSH on macOS with XQuartz, X11 forwarding requires additional setup due to macOS-specific socket handling.

**Problem:** XQuartz on macOS uses a non-standard Unix socket path (`/private/tmp/com.apple.launchd.*/org.xquartz:0`) that SSH cannot connect back to when establishing X11 forwarding tunnels.

#### Prerequisites

1. Install XQuartz:
```bash
brew install --cask xquartz
```
After installation, log out and log back in (or restart).

2. Create the standard X11 socket directory:
```bash
sudo mkdir -p /tmp/.X11-unix
sudo chmod 1777 /tmp/.X11-unix
```

3. Install socat (for socket bridging):
```bash
brew install socat
```

#### SSH Configuration

Add X11 forwarding settings to your SSH host configurations in `~/.ssh/config`:

```ssh-config
Host *
    XAuthLocation /opt/X11/bin/xauth

Host your-remote-host
    ForwardX11 yes
    ForwardX11Trusted yes
```

**Important:** Remote servers must have `xauth` installed. On Debian/Ubuntu:
```bash
sudo apt install xauth
```

#### DISPLAY Variable and Socket Bridge

Add this to your `~/.bashrc` or `~/.zshrc`:

```bash
# Fix DISPLAY for SSH X11 forwarding on macOS
if [[ "$DISPLAY" =~ ^/private/tmp/.* ]]; then
    export DISPLAY=localhost:0
    
    # Start socat bridge for X11 Unix socket if not already running
    if command -v socat >/dev/null 2>&1 && [ ! -S /tmp/.X11-unix/X0 ]; then
        XQUARTZ_SOCKET=$(echo "$DISPLAY" | sed 's|^/private||')
        if [ -S "$XQUARTZ_SOCKET" ]; then
            socat UNIX-LISTEN:/tmp/.X11-unix/X0,fork UNIX-CONNECT:"$XQUARTZ_SOCKET" >/dev/null 2>&1 &
        fi
    fi
fi
```

**Why socat is needed:** SSH expects X11 sockets in `/tmp/.X11-unix/X0`, but XQuartz creates them in `/private/tmp/com.apple.launchd.*/org.xquartz:0`. The socat bridge forwards connections between these two locations, allowing SSH's X11 forwarding tunnel to work correctly.

#### Verification

After setup, verify X11 forwarding works:

```bash
# Source your shell config
source ~/.bashrc

# Test SSH connection
ssh your-remote-host

# On remote host, check DISPLAY is set
echo $DISPLAY  # Should show: localhost:10.0 (or similar)

# Test with a GUI application
firefox &
```

#### Common Issues

- **"No xauth program; cannot forward X11"**: Install `xauth` on the remote server
- **"Connection refused"**: Ensure XQuartz is running and the socat bridge is active
- **Empty DISPLAY on remote**: Check that `ForwardX11 yes` is in your SSH config
- **Local DISPLAY shows XQuartz path**: Source your shell config or restart your terminal
