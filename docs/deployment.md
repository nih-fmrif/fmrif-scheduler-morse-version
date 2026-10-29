# OAuth 2.0 PKCE Staging Deployment - Complete Documentation

**Status:** Fully Deployed and Operational
**URL:** `https://scheduler.example.test`

---

## Quick Summary

OAuth 2.0 PKCE implementation successfully deployed on fmrif-staging with Flask backend, PostgreSQL database, and nginx reverse proxy for HTTPS support.

### Quick Reference - URLs for Testing

| URL | Purpose | Access |
|-----|---------|--------|
| `https://scheduler.example.test` | **Main Staging URL** - Start here | From NIH network / VPN |
| `https://scheduler.example.test/auth/login` | Login page with OAuth button | From NIH network / VPN |
| `https://scheduler.example.test/api/config/entra.json` | OAuth configuration (for debugging) | From NIH network / VPN |
| `http://localhost:5051/auth/login` | Direct Flask login (internal testing) | On fmrif-staging server |
| `http://localhost:5051/api/config/entra.json` | Direct OAuth config (internal testing) | On fmrif-staging server |

---

## OAuth 2.0 PKCE Flow Diagram

```
┌──────────────────────────────────────────────────────────┐
│  1. User Access Staging Domain                           │
│  https://scheduler.example.test     │
└────────────────────┬─────────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────────┐
│  2. nginx Reverse Proxy (Port 443 HTTPS)                 │
│   Terminates SSL/TLS                                     │
│   Forwards to Flask on 5051                              │
│   Adds X-Forwarded headers                               │
└────────────────────┬─────────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────────┐
│  3. Flask Login Page (Port 5051)                         │
│   Displays OAuth Button                                  │
│   Button shows "Login with NIH Credentials"              │
│   JavaScript auth-manager.js loaded                      │
└────────────────────┬─────────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────────┐
│  4. Load OAuth Configuration                             │
│  GET /api/config/entra.json                              │
│   Scope: openid profile email                            │
│   Auth Endpoint: Microsoft Entra                         │
│   Redirect URI: Configured correctly                     │
│   Client ID: Staging credentials                         │
└────────────────────┬─────────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────────┐
│  5. User Clicks "Login with NIH" Button                  │
│  Frontend generates PKCE challenge & redirect URL        │
│  JavaScript redirects to Microsoft Entra                 │
└────────────────────┬─────────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────────┐
│  6. Microsoft Entra Login Page                           │
│  https://login.microsoftonline.com/{tenant}/oauth2/...   │
│   With proper scope parameter                            │
│   PKCE code_challenge included                           │
└────────────────────┬─────────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────────┐
│  7. User Authenticates                                   │
│  • Username + Password                                   │
│  • Or: PIV Card / Multi-Factor Authentication            │
└────────────────────┬─────────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────────┐
│  8. Redirect Back to Application                         │
│  https://scheduler.example.test/    │
│  auth/callback?code=xxx&state=yyy                        │
│   Authorization code included                            │
└────────────────────┬─────────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────────┐
│  9. Frontend Process Callback                            │
│  JavaScript extracts code from URL                       │
│  Sends code + PKCE verifier to token endpoint            │
└────────────────────┬─────────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────────┐
│  10. Application Processes Callback                      │
│   Session established with user info                     │
│   Tokens stored securely                                 │
│   User redirected to dashboard                           │
└──────────────────────────────────────────────────────────┘
```

---

## Deployment Components

### 1. Flask Application (fmrif-staging)
- **Language:** Python 3.11
- **Port:** 5051 (HTTP, internal only)
- **Status:** Running (PID 13735)
- **Command:** `/bin/bash /home/leejo/fmrif-scheduler-morse-version/scripts/serve.sh`
- **Logs:** `/tmp/flask-staging.log`

### 2. PostgreSQL Database (fmrif-staging)
- **Port:** 5432
- **Database:** fmrif_scheduler
- **User:** postgres
- **Password:** replace-with-pgpassword
- **Tables:** 22 (all initialized)
- **Status:** Running

### 3. nginx Reverse Proxy (fmrif-staging)
- **Port:** 80 (HTTP) → redirects to HTTPS
- **Port:** 443 (HTTPS with SSL)
- **Certificate:** `/etc/ssl/certs/2025-nimh.nih.combined.pem`
- **Certificate Source:** Copied from fmrif-dev at `/home/fmrifadmin/my_root/etc/ssl/certs/2025-nimh.nih.combined.pem`
- **Upstream:** 127.0.0.1:5051 (Flask)
- **Config:** `/etc/nginx/sites-available/default`
- **Status:** Running (master + 2 workers)

### 4. OAuth Configuration
- **Client ID:** replace-with-entra--client-id (Staging)
- **Tenant ID:** replace-with-entra--tenant-id
- **Redirect URI:** https://scheduler.example.test/auth/callback
- **Authorization Endpoint:** https://login.microsoftonline.com/replace-with-entra--tenant-id/oauth2/v2.0/authorize
- **Token Endpoint:** https://login.microsoftonline.com/replace-with-entra--tenant-id/oauth2/v2.0/token
- **Callback Route:** GET /auth/callback (handles OAuth redirect from Entra)
- **OAuth Scope:** `openid profile email offline_access` (OIDC + refresh token support)

---

## Issues Encountered & Solutions

### Issue 1: OAuth Callback 404 Error (Not Found)
**Problem:** Microsoft Entra redirects back to `/auth/callback?code=xxx&state=yyy` but the application returns 404 — the endpoint doesn't exist.

**Root Cause:** The Flask auth blueprint had routes for `/login`, `/session`, and `/logout`, but no `/callback` route to handle the OAuth redirect from Entra.

**Solution:**
1. Added `/auth/callback` route in `scheduler/auth/views.py` that renders the same `auth/login.html` template
2. When the page loads at `/auth/callback?code=xxx`, the JavaScript (auth-manager.js) detects the `code=` parameter and automatically:
   - Extracts the authorization code from the URL
   - Exchanges it for tokens (access_token, id_token, refresh_token) via POST to Entra's token endpoint
   - Stores tokens in sessionStorage
   - Establishes a server session by POSTing to `/auth/session`
   - Redirects to the home page

The PKCE verifier generated on the login page persists in sessionStorage across page navigation, so it's available when needed for the token exchange.

---

### Issue 2: Missing `token_endpoint` in OAuth Config
**Problem:** The `/api/config/entra.json` endpoint doesn't include `token_endpoint`, but the JavaScript (auth-manager.js line 294) tries to `fetch(entraConfig.token_endpoint, ...)`. This causes an error because `token_endpoint` is `undefined`.

**Solution:**
Added `token_endpoint` to the `/api/config/entra.json` response in `scheduler/app.py`:
```python
"token_endpoint": f"https://login.microsoftonline.com/{settings.entra.tenant_id}/oauth2/v2.0/token",
```

This follows the same pattern as `authorization_endpoint` — constructed dynamically from the tenant ID.

---

**Why "openid profile email offline_access"?**
- `openid` - Required for OpenID Connect flow. Tells Microsoft Entra to return an ID token with user authentication
- `profile` - Requests user profile information (name, picture, preferred_username, etc.)
- `email` - Requests user email address
- `offline_access` - Requests a refresh token so the application can obtain new access tokens without requiring the user to log in again

These are standard OIDC scopes for user identity plus refresh capability. NIH team does NOT need to make any changes - this is configured server-side and automatically requested by our application. Microsoft Entra will return these claims in the ID token and will include a refresh_token in the token response (if offline_access is requested).

---

## Environment Configuration

**File:** `/home/leejo/fmrif-scheduler-morse-version/.env`

```
FLASK_APP=scheduler.app:create_app
PGHOST=localhost
PGPORT=5432
PGUSER=postgres
PGPASSWORD=replace-with-pgpassword
PGDATABASE=fmrif_scheduler
ENTRA__CLIENT_ID=replace-with-entra--client-id
ENTRA__TENANT_ID=replace-with-entra--tenant-id
ENTRA__CLIENT_SECRET=replace-with-entra--client-secret
ENTRA__DISCOVERY_URL=https://login.microsoftonline.com/replace-with-entra--tenant-id/v2.0/.well-known/openid-configuration
ENTRA__REDIRECT_URI=https://scheduler.example.test/auth/callback
ENTRA__SCOPE=openid profile email offline_access
RBAC__SUPERUSER_MODE=false
SERVER__SERVER_NAME=
```

### Optional: OAuth Test Credentials

For end-to-end testing with Playwright, add these variables to `.env`:

```
# Only set if you have valid test credentials
# Leave commented out if testing without credentials (test will skip)
# Note: Username should NOT include @nih.gov - the test adds it automatically
OAUTH_TEST_USERNAME=test_username
OAUTH_TEST_PASSWORD=replace-with-oauth-test-password
```

**How it works:**
- Playwright test reads `OAUTH_TEST_USERNAME` and `OAUTH_TEST_PASSWORD` from `.env`
- Uses `os.getenv()` to read environment variables
- If credentials are not set, test automatically skips with message: "OAuth test credentials not found"
- When credentials are provided, test runs full OAuth flow: login → Microsoft Entra → callback → dashboard
- Test automatically appends `@nih.gov` to username (NIH Entra requirement)

---

## Deployment Steps (For Reproduction)

### 1. SSH to fmrif-staging
```bash
ssh fmrif-staging
cd /home/leejo/fmrif-scheduler-morse-version
```

### 2. Create Python venv
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Install & Configure PostgreSQL
```bash
sudo apt-get install postgresql-15
sudo -u postgres createdb fmrif_scheduler
export PGHOST=localhost PGPORT=5432 PGUSER=postgres PGPASSWORD=replace-with-pgpassword PGDATABASE=fmrif_scheduler
bash sql/000-init.sh
```

### 4. Configure .env
Create `.env` with values from "Environment Configuration" section above

### 5. Install & Configure nginx
```bash
sudo apt-get install nginx
# Needs ssl cert
# Copy nginx config to /etc/nginx/sites-available/default
sudo nginx -t
sudo systemctl restart nginx
```

### 6. Install Flask as Systemd Service
Systemd ensures Flask automatically restarts after server reboot.

```bash
# Copy service file to systemd directory
sudo cp fmrif-flask.service /etc/systemd/system/

# Enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable fmrif-flask
sudo systemctl start fmrif-flask

# Verify it's running
sudo systemctl status fmrif-flask
```

**Alternative (Legacy): Start Flask with nohup** (not recommended for production)
```bash
nohup /bin/bash /home/leejo/fmrif-scheduler-morse-version/scripts/serve.sh > /tmp/flask-staging.log 2>&1 &
```

### 7. Verify
```bash
curl -k https://scheduler.example.test/auth/login
# Should return 200 with login page HTML
```

---

## Testing & Verification

### Health Checks
```bash
# Flask running
ps aux | grep "flask run"

# PostgreSQL running
ps aux | grep postgres

# nginx running
ps aux | grep nginx

# Ports listening
ss -tlnp | grep -E ':(80|443|5051)'
```

### Functional Tests
```bash
# Login page loads
curl -k https://scheduler.example.test/auth/login | grep "Login with NIH"

# OAuth config endpoint
curl -k https://scheduler.example.test/api/config/entra.json | jq '.authorization_endpoint'

# Python unit tests
cd /home/leejo/fmrif-scheduler-morse-version
source .venv/bin/activate
python -m pytest tests/python/ -q
# Expected: 43 passed

# OAuth end-to-end test with Playwright
# IMPORTANT: Application is only accessible from:
#   1. fmrif-staging server (localhost:5051)
#   2. NIH network or VPN
#   3. SSH tunnel from local machine
#
# Choose ONE execution option below:

# ═══════════════════════════════════════════════════════════════════
# OPTION 1: Run test ON fmrif-staging (RECOMMENDED)
# ═══════════════════════════════════════════════════════════════════
ssh fmrif-staging
cd /home/leejo/fmrif-scheduler-morse-version
source .venv/bin/activate

# Install Playwright (first time only)
pip install playwright
python -m playwright install chromium

# Set test credentials
export OAUTH_TEST_USERNAME=test_username
export OAUTH_TEST_PASSWORD=replace-with-oauth-test-password

# Run test against local Flask (localhost:5051)
# No VPN needed - runs directly on server
python -m pytest tests/playwright/test_oauth_flow.py -v --headed

# ═══════════════════════════════════════════════════════════════════
# OPTION 2: Run test from machine WITH NIH VPN
# ═══════════════════════════════════════════════════════════════════
# Prerequisites:
#   - On NIH VPN
#   - Playwright installed locally
#   - Test credentials available

export STAGING_URL=https://scheduler.example.test
export OAUTH_TEST_USERNAME=test_username
export OAUTH_TEST_PASSWORD=replace-with-oauth-test-password

python -m pytest tests/playwright/test_oauth_flow.py -v --headed

# ═══════════════════════════════════════════════════════════════════
# OPTION 3: Run test via SSH tunnel (NO VPN required)
# ═══════════════════════════════════════════════════════════════════
# Terminal 1: Create SSH tunnel
ssh -L 8080:localhost:5051 fmrif-staging
# Keep this terminal open - tunnel stays active

# Terminal 2: Run test pointing to tunnel
export STAGING_URL=http://localhost:8080
export OAUTH_TEST_USERNAME=test_username
export OAUTH_TEST_PASSWORD=replace-with-oauth-test-password

python -m pytest tests/playwright/test_oauth_flow.py -v --headed

# When done, close terminal 1 to close tunnel
```

---

## Important Files & Locations

| Item | Location |
|------|----------|
| Application Code | `/home/leejo/fmrif-scheduler-morse-version` |
| Environment Config | `/home/leejo/fmrif-scheduler-morse-version/.env` |
| Flask Logs | `/tmp/flask-staging.log` |
| Systemd Service | `/etc/systemd/system/fmrif-flask.service` |
| Systemd Service Template | `/home/leejo/fmrif-scheduler-morse-version/fmrif-flask.service` |
| nginx Config | `/etc/nginx/sites-available/default` |
| SSL Certificate | `/tmp/2026-nimh.nih.combined.pem` |
| Database Init Script | `sql/000-init.sh` |
| OAuth End-to-End Test | `tests/playwright/test_oauth_flow.py` |

---

## Restart Procedures

### Restart Flask (with Systemd)
```bash
sudo systemctl restart fmrif-flask
# Verify
sudo systemctl status fmrif-flask
```

### Restart Flask (Legacy - nohup method)
```bash
pkill -f "flask run"
sleep 2
cd /home/leejo/fmrif-scheduler-morse-version
nohup /bin/bash /home/leejo/fmrif-scheduler-morse-version/scripts/serve.sh > /tmp/flask-staging.log 2>&1 &
```

### Restart PostgreSQL
```bash
sudo systemctl restart postgresql
```

### Restart nginx
```bash
sudo systemctl restart nginx
```

### Verify All Services
```bash
curl -k -I https://scheduler.example.test/auth/login
# Should return 200 OK
```

---

## Future Debugging

**If login page doesn't load:**
- Check Flask is running: `ps aux | grep flask`
- Check logs: `tail -50 /tmp/flask-staging.log`
- Check .env is correct: `cat .env | grep ENTRA`

**If HTTPS fails:**
- Check nginx: `ps aux | grep nginx`
- Check certificate exists: `ls -la /tmp/2026-nimh.nih.combined.pem`
- Check nginx config: `sudo nginx -t`

**If OAuth button doesn't redirect:**
- Check authorization_endpoint in config: `curl -k https://scheduler.example.test/api/config/entra.json`
- Check browser console for JavaScript errors
- Verify RBAC__SUPERUSER_MODE=false in .env

**If database issues:**
- Check PostgreSQL running: `ps aux | grep postgres`
- Check connection: `PGPASSWORD=replace-with-pgpassword psql -h localhost -U postgres -d fmrif_scheduler -c "SELECT 1"`
- Check tables: `PGPASSWORD=replace-with-pgpassword psql -h localhost -U postgres -d fmrif_scheduler -c "\dt"`

---
