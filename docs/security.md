# Security Guide

This document describes the security controls currently implemented in the Scheduler
application, how to configure them, and what attack classes they are designed to
mitigate.

It is based on the current code in:

- `scheduler/app.py`
- `scheduler/config.py`
- `scheduler/auth/views.py`
- `scheduler/auth/session.py`
- `scheduler/auth/jwt_utils.py`
- `scheduler/auth/oidc.py`
- `scheduler/auth/pkce.py`
- `scheduler/logging.py`

## Scope and Threat Model

The app is a server-rendered Flask application with:

- Microsoft Entra OIDC login
- server-side sessions
- optional bearer-token authentication for API-style access
- role and active-user checks backed by database state

Primary threats addressed by built-in controls:

- forged or replayed authentication artifacts
- session hijacking and fixation
- CSRF on state-changing routes
- clickjacking and browser-side script/content injection
- brute-force/abuse on authentication endpoints
- accidental insecure deployment configuration
- secret leakage through logs

## Security Controls Overview

| Control | Key Configuration | Prevents / Reduces |
| --- | --- | --- |
| OIDC authorization code flow with PKCE + state + nonce | `ENTRA__*` | code interception, login CSRF, token replay/substitution |
| JWT signature + issuer + audience + algorithm verification | `ENTRA__ALLOWED_ALGORITHMS`, `ENTRA__ALLOWED_AUDIENCES`, `ENTRA__TENANT_ID`, `ENTRA__CLIENT_ID` | token forgery, key/alg confusion, token substitution across apps/issuers |
| Strict identity claim validation (`preferred_username` as email) | none (code-level) | malformed-identity acceptance, domain policy bypass via malformed claims |
| Bearer auto-provision policy gates | `ENTRA__BEARER_AUTO_PROVISION_*` | unauthorized account creation from otherwise-valid tokens |
| Server-side session + hardened cookie flags + SID rotation | `SESSION__*` | session theft impact, session fixation, CSRF risk (via SameSite) |
| CSRF tokens on forms | Flask-WTF + `SECRET_KEY` | cross-site form submission attacks |
| Signed action links for join/deny flows | `CORE__SECRET_KEY` | tampering with approval-action URLs |
| Browser hardening headers (CSP, HSTS, XFO, nosniff, referrer) | `SECURITY__*` | XSS blast radius, clickjacking, MIME confusion, TLS downgrade |
| Auth endpoint rate limiting | `SECURITY__AUTH_RATE_LIMIT_*` | brute force and high-rate auth abuse |
| Mock auth endpoint guardrails | `AUTH_TEST__*` | unauthorized test-session minting (when correctly configured) |
| Startup validation guardrails | `AUTH_TEST__ENABLED`, `CORE__*`, `SESSION__*`, `ENTRA__*` | insecure production startup due to config drift |
| Sensitive log redaction | `LOGGING__REVEAL_SENSITIVE_DATA`, `LOGGING__REDACTION_TEXT` | accidental credential/token leakage in logs |

## Authentication and Identity Controls

### 1) OIDC Flow: Authorization Code + PKCE + State + Nonce

Implemented in `scheduler/auth/views.py`, `scheduler/auth/pkce.py`, and
`scheduler/auth/oidc.py`.

Behavior:

- login starts at `/auth/entra`
- generates high-entropy PKCE verifier/challenge (S256)
- stores `state`, `nonce`, and `code_verifier` server-side
- callback validates `state`, exchanges code for token, validates JWT, checks nonce
- state records are single-use and expire after 10 minutes

Configuration:

- `ENTRA__CLIENT_ID` (required for production)
- `ENTRA__TENANT_ID` (required for production)
- `ENTRA__CLIENT_SECRET` (required for confidential client exchange)
- `ENTRA__DISCOVERY_URL` (required for production)
- `ENTRA__REDIRECT_URI` (required for production)
- `ENTRA__SCOPE` (default includes `openid profile email offline_access`)
- `ENTRA__JWKS_CACHE_TTL` (JWKS/discovery cache lifetime)

Attack classes mitigated:

- OAuth authorization-code interception (PKCE)
- CSRF against login callback (state)
- ID token replay/substitution across auth attempts (nonce)

### 2) JWT Verification and Claim Validation

Implemented in `scheduler/auth/jwt_utils.py`.

Behavior:

- fetches signing keys from Entra discovery/JWKS
- validates `kid`, signature, issuer, audience, and allowed algorithms
- restricts accepted algorithms via server-side allowlist
- requires `preferred_username` claim
- validates `preferred_username` is a valid email address
- logs claim-format failures at error level

Configuration:

- `ENTRA__ALLOWED_ALGORITHMS` (default `["RS256"]`)
- `ENTRA__ALLOWED_AUDIENCES` (optional extra accepted audiences)
- implied issuer from `ENTRA__TENANT_ID`

Attack classes mitigated:

- token forgery
- accepting tokens signed with unexpected algorithm
- accepting tokens for the wrong audience or issuer
- malformed or ambiguous identity claims

### 3) Stable User ID Derivation

Implemented through `scoped_user_id_from_identifier(...)` in `scheduler/logic.py`
and used by `user_from_claims(...)`.

Behavior:

- derives user IDs from full identifier, not just local-part
- adds short hash component to avoid local-part collisions across domains

Attack classes mitigated:

- identity collision where two domains share same local-part (for example,
  `alice@a.example` vs `alice@b.example`)

### 4) Bearer Auto-Provision Policy

Implemented in `scheduler/auth/session.py`.

Behavior:

- existing user emails in DB are always allowed
- new user creation from bearer-authenticated requests is blocked unless enabled
- optional domain allowlist and claim-group gate can be required

Configuration:

- `ENTRA__BEARER_AUTO_PROVISION_ENABLED` (default `false`)
- `ENTRA__BEARER_AUTO_PROVISION_DOMAINS` (optional JSON list)
- `ENTRA__BEARER_AUTO_PROVISION_GROUPS` (optional JSON list)

Attack classes mitigated:

- unauthorized account population by valid-but-unapproved identities
- accidental broad trust of all tenant users

## Session and Request Integrity

### 1) Server-Side Sessions and Cookie Hardening

Implemented in `scheduler/app.py` and `scheduler/config.py`.

Behavior:

- session state stored server-side (`SESSION_TYPE=sqlalchemy`)
- hardened cookie defaults:
  - `Secure`
  - `HttpOnly`
  - `SameSite=Strict`
- session lifetime is configurable (`PERMANENT_SESSION_LIFETIME`)
- best-effort session ID rotation on login boundary
- session active-status lookup fails closed (inactive on DB lookup error)

Configuration:

- `SESSION__COOKIE_NAME` (default `dsid`)
- `SESSION__COOKIE_SECURE` (default `true`)
- `SESSION__COOKIE_HTTPONLY` (default `true`)
- `SESSION__COOKIE_SAMESITE` (default `Strict`)
- `SESSION__PERMANENT_LIFETIME` (default 8h)
- `SESSION__TYPE` (default `sqlalchemy`)
- `SESSION__USE_SIGNER` (default `true`)
- `SESSION__SQLALCHEMY_TABLE` (default `site_sessions`)

Attack classes mitigated:

- session fixation
- some cookie theft abuse paths (reduced by HttpOnly/Secure)
- CSRF impact for session cookie flows (reduced by SameSite)

### 2) CSRF Protection

Implemented via Flask-WTF forms (`FlaskForm`) including a dedicated
`CsrfOnlyForm` for routes that only need CSRF validation.

Behavior:

- state-changing form routes must present valid CSRF tokens
- `/auth/logout` explicitly validates CSRF token

Attack classes mitigated:

- cross-site request forgery on authenticated browser sessions

### 3) Signed URL Actions

Implemented via `itsdangerous.URLSafeSerializer` in `scheduler/app.py` and
`scheduler/logic.py`.

Behavior:

- join/deny action links are signed before issuance and verified on receipt
- tampered tokens fail verification

Attack classes mitigated:

- link parameter tampering for approval/denial actions

## Browser and Transport Hardening

Implemented in `scheduler/app.py` response middleware and `SecurityConfig`.

Headers and controls:

- `Content-Security-Policy` (with per-request nonce support for style policy)
- `Strict-Transport-Security` (HTTPS responses only)
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`

Configuration:

- `SECURITY__ENABLE_CSP` (default `true`)
- `SECURITY__CSP_REPORT_ONLY` (default `false`)
- `SECURITY__CSP_POLICY` (default restrictive policy with nonce placeholder)
- `SECURITY__ENABLE_HSTS` (default `true`)
- `SECURITY__HSTS_MAX_AGE` (default `63072000`)
- `SECURITY__HSTS_INCLUDE_SUBDOMAINS` (default `true`)
- `SECURITY__HSTS_PRELOAD` (default `false`)
- `SECURITY__FRAME_OPTIONS` (default `DENY`)
- `SECURITY__CONTENT_TYPE_OPTIONS` (default `nosniff`)
- `SECURITY__REFERRER_POLICY` (default `strict-origin-when-cross-origin`)

Attack classes mitigated:

- clickjacking
- script/content injection impact (reduced via CSP)
- MIME sniffing-based execution
- protocol downgrade after initial secure visit (HSTS)

## XSS Rendering Guardrails and Anti-Regression Checks

To keep template/DOM rendering safe over time, the repo now enforces
anti-regression checks implemented by `scripts/check-no-unsafe-html-sinks.sh`,
which runs in:

- pre-commit hook `no-unsafe-html-sinks`
- CI workflow step `Run XSS sink guardrails`

The check blocks three high-risk patterns unless explicitly allowlisted:

1. `|safe` in `scheduler/templates/*.html`
2. DOM HTML sinks in frontend code (`innerHTML`, `outerHTML`,
   `insertAdjacentHTML`, `document.write`)
3. New `markupsafe.Markup(...)` usage in Python

Why this exists:

- XSS risk in this app is not limited to embedding scenarios; any page render can
  be affected when untrusted data reaches HTML sinks.
- These patterns are convenient and tend to reappear during normal feature work
  unless guardrails are automated.

Current approved exceptions are intentionally narrow and documented in
`scripts/check-no-unsafe-html-sinks.sh` (for example the controlled
`<sr-only>` nav helper and specific dialog/grid rendering paths that depend on
escaped or trusted server markup).

Expected developer workflow:

- default to Jinja auto-escaping in templates (no `|safe`)
- prefer `textContent`/`innerText` for plain text in JS
- if HTML rendering is required, escape all untrusted values first and then
  update the allowlist with reviewer justification

## Authentication Abuse Controls

### Auth Endpoint Rate Limiting

Implemented in `scheduler/auth/views.py` for:

- `POST /auth/session`
- `POST` and `DELETE /auth/test/session`

Behavior:

- fixed-window in-memory limiter keyed by client identifier and scope
- returns HTTP 429 on threshold exceedance

Configuration:

- `SECURITY__AUTH_RATE_LIMIT_ENABLED` (default `true`)
- `SECURITY__AUTH_RATE_LIMIT_WINDOW_SECONDS` (default `60`)
- `SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS` (default `30`)

Attack classes mitigated:

- credential stuffing velocity
- noisy token replay attempts

Operational note:

- this limiter is process-local and memory-backed
- for production-scale defense, pair with ingress/API gateway rate limiting

## Mock/Test Authentication Controls

Implemented in `POST|DELETE /auth/test/session`.

Behavior:

- endpoint is hidden as `404` unless `AUTH_TEST__ENABLED=true`
- requires `X-Test-Auth-Secret` and constant-time compare
- can mint role-bearing test sessions from configured profiles

Configuration:

- `AUTH_TEST__ENABLED` (default in code: `false`)
- `AUTH_TEST__SHARED_SECRET` (required when enabled)
- `AUTH_TEST__SEED_GROUPS`
- `AUTH_TEST__PROFILES` (optional profile overrides)

Operational guidance:

- keep `AUTH_TEST__ENABLED=false` in production
- rotate and tightly scope `AUTH_TEST__SHARED_SECRET` anywhere enabled
- restrict network exposure to this route in non-local environments

Attack classes mitigated:

- unauthorized test-session minting (when disabled or properly secret-protected)

## Startup Guardrails and Safe Defaults

Implemented in `Settings.validate_required_settings(...)`.

When `APP_ENV=production`, startup validation enforces:

- non-placeholder Entra client ID
- non-placeholder Entra tenant ID
- Entra discovery URL set
- Entra redirect URI set
- `CORE__DEBUG=false`
- non-default `CORE__SECRET_KEY`
- `SESSION__COOKIE_SECURE=true`

Additional `APP_ENV=production` guardrails:

- `APP_ENV` must not be `production` when `AUTH_TEST__ENABLED=true`
- Mailpit cannot be used (`MAILPIT__*` unset and `MAIL__SERVER` not set to `mailpit` or `mailpit_app`)
- `MAIL__DEFAULT_SENDER` is always required

When `AUTH_TEST__ENABLED=true`, startup validation enforces:

- non-empty `AUTH_TEST__SHARED_SECRET`

Attack classes mitigated:

- insecure production startup due to missing/bad auth and session configuration

## Logging and Data Exposure Controls

Implemented in `scheduler/logging.py`.

Behavior:

- centralized sensitive-data redaction filter applied to app/root loggers
- redacts common tokens/secrets in:
  - free-text strings
  - query strings
  - key-value message payloads
- defaults to redacting auth artifacts like:
  - access/id/refresh tokens
  - `client_secret`
  - `code_verifier`
  - auth headers/cookies
  - test-auth secret
  - OAuth state/code

Configuration:

- `LOGGING__LEVEL` (default `INFO`)
- `LOGGING__REVEAL_SENSITIVE_DATA` (default `false`)
- `LOGGING__REDACTION_TEXT` (default `[REDACTED]`)

Attack classes mitigated:

- credential and token leakage through logs

## Reverse Proxy Trust Configuration

Implemented by optional Werkzeug `ProxyFix` setup in `scheduler/app.py`.

Configuration:

- `MMSCHED_X_FORWARDED_FOR`
- `MMSCHED_X_FORWARDED_PROTO`
- `MMSCHED_X_FORWARDED_HOST`
- `MMSCHED_X_FORWARDED_PORT`
- `MMSCHED_X_FORWARDED_PREFIX`

These values must match your real trusted proxy chain depth. Incorrect values can
cause request metadata trust errors (scheme/host/client attribution issues).

## Recommended Production Baseline

At minimum, ensure:

```env
APP_ENV=production
AUTH_TEST__ENABLED=false

CORE__DEBUG=false
CORE__SECRET_KEY=<long-random-secret>

SESSION__COOKIE_SECURE=true
SESSION__COOKIE_HTTPONLY=true
SESSION__COOKIE_SAMESITE=Strict

ENTRA__CLIENT_ID=<app-client-id>
ENTRA__TENANT_ID=<tenant-id>
ENTRA__CLIENT_SECRET=<secret>
ENTRA__DISCOVERY_URL=https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration
ENTRA__REDIRECT_URI=https://<your-host>/auth/callback
ENTRA__ALLOWED_ALGORITHMS=["RS256"]

ENTRA__BEARER_AUTO_PROVISION_ENABLED=false
# If enabling auto-provision:
# ENTRA__BEARER_AUTO_PROVISION_DOMAINS=["nih.gov"]
# ENTRA__BEARER_AUTO_PROVISION_GROUPS=["<entra-group-id>"]

SECURITY__ENABLE_CSP=true
SECURITY__CSP_REPORT_ONLY=false
SECURITY__ENABLE_HSTS=true
SECURITY__AUTH_RATE_LIMIT_ENABLED=true

LOGGING__REVEAL_SENSITIVE_DATA=false
```

## Current Limitations and Recommended Compensating Controls

Built-in controls are strong for app-layer defaults, but you should still add
platform controls:

- enforce TLS termination and modern ciphers at ingress
- add edge/API rate limiting and WAF rules
- route auth/security events to centralized SIEM
- run dependency scanning and SBOM generation in CI
- limit network access to internal/test-only routes

These controls are complementary and reduce residual risk from misconfiguration,
zero-days, and volumetric attack patterns.
