# Mail Configuration Notes

## Decision Log
- **2026-03-01 10:10 UTC**: Verified tracked config model maps sender via `MailConfig.default_sender` and validates `MAIL__DEFAULT_SENDER`; no active `CORE__SITE_SENDER` path in source.
- **2026-03-01 10:12 UTC**: Identified `.env.sample.local` ambiguity: `MAIL__PORT` (app SMTP target) and `MAILPIT__SMTP_PORT` (Mailpit host binding) are defined in different sections, making intent less obvious for local Mailpit users.
- **2026-03-01 10:18 UTC**: Consolidated `MAILPIT__*` service port placeholders into Mail section in `.env.sample.local` and added comments clarifying compose vs host-mode behavior.

## Current State
- Mail sender is sourced from `MAIL__DEFAULT_SENDER` and mapped into Flask-Mail via `MAIL_DEFAULT_SENDER`.
- For SMTP transport, the app consumes `MAIL__SERVER`, `MAIL__PORT`, `MAIL__SUPPRESS_SEND`, and optional `MAIL__USERNAME` / `MAIL__PASSWORD`.
- `MAIL__PORT` and `MAILPIT__SMTP_PORT` are not duplicates:
  - `MAIL__PORT` is app-level SMTP destination.
  - `MAILPIT__SMTP_PORT` controls where host-mode app should reach Mailpit.

## Consolidation Outcome
- `.env.sample.local` now groups Mailpit host endpoints near Mail settings instead of mixing them in Database settings.
- Comments explicitly describe:
  - `MAIL__*` as application SMTP.
  - Host-mode: `MAIL__SERVER=localhost` + `MAIL__PORT=${MAILPIT__SMTP_PORT}`.
  - Compose-mode: scheduler container overrides `MAIL__SERVER=mailpit` and `MAIL__PORT=1025` in `compose.yaml`.
- No behavior change in code paths; only documentation/sample configuration clarity.

## Residual checks
- `CORE__SITE_SENDER` is only referenced in an untracked local file (`.env.codex.backup`) and not in tracked source configuration.
