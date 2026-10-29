# Deployment Considerations

This document is for general deployment-adjacent details that are easy to forget
and easy to trip over. It is not the final environment-specific deployment runbook.

The real production deployment on Debian stable with system-installed services
should be documented separately.

## Serving Modes

- Host mode:
  - `pixi run serve` uses Flask/Werkzeug.
  - startup waits for local readiness and then runs the edge-header probe automatically.
  - Best for fast local iteration and debugging.
- Host parity mode:
  - `pixi run serve-gunicorn` uses Gunicorn without nginx.
  - it uses the same startup gate as `pixi run serve`.
  - Useful when you want to reproduce worker/time-out behavior locally.
- Full compose mode:
  - `bash run-compose.sh`
  - nginx is host-facing.
  - Gunicorn serves the Flask app behind nginx.
  - Compose services default to `linux/amd64`.
  - The app container builds from the shared repository `pixi.toml`, narrowing
    the copied in-image manifest to `linux-64`, so host and container workflows
    use one tracked dependency manifest while Docker still resolves the x86
    Linux environment directly.

## Port Ownership

Treat `APP_PORT` as the user-facing application port.

That means:

- In host mode, `APP_PORT` is the Flask or Gunicorn port directly.
- In full compose mode, `APP_PORT` belongs to nginx, not the app container.
- The internal app container port stays fixed at `5051`.
- nginx listens on fixed container port `80`.

Recommended mental model:

```text
host client -> localhost:APP_PORT -> nginx:80 -> app:5051
```

This keeps the external access point stable even when the internal topology changes.

## Proxy Headers

In proxied setups, the application may need to trust forwarded request metadata:

- client IP
- scheme (`http` vs `https`)
- host
- sometimes port

In this repo, the compose setup currently trusts:

- `X-Forwarded-For`
- `X-Forwarded-Proto`
- `X-Forwarded-Host`

It does not currently trust `X-Forwarded-Port` in local compose mode.

## Why `X-Forwarded-Port` Is Easy To Get Wrong

Docker port publishing can hide the real external port from nginx.

Example:

```text
host 21037 -> nginx container 80
```

nginx sees the request on port `80`, because that is its container port.
If nginx forwards `X-Forwarded-Port: 80`, the backend may incorrectly believe
the user connected to port `80` instead of `21037`.

That can lead to:

- wrong absolute URLs
- wrong redirect targets
- wrong callback URLs
- confusing origin or host reconstruction bugs

If the external port matters, preserving `Host` or `X-Forwarded-Host` with the
host:port value is often safer in Docker-based local proxy setups.

## Gunicorn vs Werkzeug

Werkzeug is convenient because it provides:

- a lighter local loop
- easier debug behavior
- automatic reload ergonomics

Gunicorn is useful because it is closer to deployment behavior:

- worker model
- request handling closer to production
- timeout behavior
- fewer surprises when running behind a real reverse proxy

Recommended use:

- Use Werkzeug for fast local development.
- Use Gunicorn for parity checks and for the full compose stack.
- Do not rely on Werkzeug as the only validation path before deployment.
- Keep the Docker path on `linux/amd64` when deployment expectations are x86,
  so architecture-specific breakage shows up in the compose path instead of
  being hidden behind native-arm development.

## Reverse Proxy Validation

Things that can pass in direct-app testing but fail in real deployments:

- missing or wrong forwarded headers
- wrong scheme reconstruction
- wrong host/port reconstruction
- CSP/header differences at the final edge
- proxy buffering or timeout behavior

When validating deployment-adjacent behavior, prefer exercising the app through
the reverse proxy path rather than only hitting the app server directly.

For header validation at the final responder, use:

```bash
python3 scripts/check-edge-security-headers.py
```

Outside production, the script defaults to `http://localhost:${APP_PORT}`. In
production, it derives the target from `ENTRA__REDIRECT_URI` by stripping
`/auth/callback`. Override `--base-url` only when you intentionally want to
probe a different edge. Point the script at the compose nginx URL or a deployed
URL to confirm the final served response still exposes exactly one CSP authority
and the expected scheme-sensitive transport headers.

## CSP And Proxy Interactions

The app sets CSP itself. That means deployers should be careful about:

- proxies adding a second CSP header
- proxies overwriting the app CSP
- stale assets or stale HTML causing policy mismatches
- local tests validating app-only responses while missing final-edge changes

If the final deployment edge also manages CSP, that should be deliberate and
documented in the environment-specific deployment runbook.

The app now enforces a nonce-backed strict script policy by default, so any edge
that rewrites HTML or script tags is more likely to break the page immediately.
That is desirable, but it raises the importance of running the final edge-header
probe from the real deployment environment rather than assuming the host-mode
startup gate is enough.

The default policy sends Reporting API violations to `/csp-report` via
`report-to csp-endpoint` plus `Reporting-Endpoints`. Reports are redacted,
stored, and shown in the Admin Panel. That gives deployers a browser-side
signal when the final edge differs from what the app expected.

## Operational Defaults Worth Remembering

- Full compose mode is the best local approximation of deployment in this repo.
- Host mode is intentionally lighter weight and not identical.
- `APP_PORT` should be thought of as the external entry port, not the app container port.
- If a bug only appears behind a proxy, reproduce it through nginx first.
- If a bug only appears under concurrency or worker isolation, reproduce it under Gunicorn.
