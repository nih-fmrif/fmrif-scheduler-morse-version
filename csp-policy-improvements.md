# CSP Policy Improvements

## Current Baseline

- Application responses set `Content-Security-Policy` in `scheduler/app.py`.
- Tracked templates do not use inline `<style>` blocks or `style=` attributes.
- The default policy is now nonce-backed for scripts: `script-src 'self' 'nonce-{nonce}' 'strict-dynamic'`, plus `script-src-attr 'none'`, `style-src 'self'`, and `style-src-attr 'none'`.
- Rendered pages attach the request nonce to every `<script>` tag, including the non-executable JSON bootstrap tags used for page state.
- CSP reports are accepted at `/csp-report` via the Reporting API, redacted before storage, written to the database, and surfaced in the Admin Panel.
- Static asset URLs carry a deploy-scoped version query parameter derived from `STATIC_ASSET_VERSION` or the current git SHA.
- `scripts/check-csp-inline-style-nonce.sh` now fails fast if a tracked template introduces any inline style tag or style attribute.
- The dev compose stack now includes nginx in front of the app so reverse-proxy header behavior can be exercised locally instead of only in deployment.

## Current Assessment

- App-side CSP correctness is strong now. The default policy is nonce-backed for scripts, tracked templates no longer rely on inline styles, repo guardrails cover the common regression paths, and browser smoke tests exercise the main pages that matter.
- The main remaining risks are no longer "template nonce mismatch" bugs. They are mostly final-edge deployment correctness, non-Chromium validation of the JSON bootstrap tags under the stricter script policy, and the operational question of how aggressively to review/retain CSP reports.
- CSP remains a containment and regression-detection layer, not the primary trust boundary. Escaping, authorization, and avoiding unsafe DOM sinks still matter more than whether markup is server-rendered or hydrated later.

## Active Execution Plan

- [x] Step 1: Consolidate base-URL configuration and root-only deployment assumptions.
  - Remove `BASE_URL`.
  - Replace `PLAYWRIGHT_BASE_URL` with `TEST_BASE_URL` in higher-level test tooling.
  - Remove `SERVER__APPLICATION_ROOT`, Flask `APPLICATION_ROOT` plumbing, the `#app-root` data island, and related JS path-prefix logic.
- [x] Step 2: Add fail-fast edge-header validation using a consolidated target derivation strategy.
  - In production, derive the edge-check target from `ENTRA__REDIRECT_URI` by stripping `/auth/callback`.
  - Validate that `ENTRA__REDIRECT_URI` parses and ends with `/auth/callback`.
  - Outside production, fall back to `http://localhost:${APP_PORT}`.
- [x] Step 3: Add DB-backed CSP reporting and surface it in the Admin Panel.
- [x] Step 4: Add deploy-scoped static asset versioning using a git SHA or deploy version.
- [x] Step 5: Expand CSP/runtime smoke coverage to auth callback, template editor, and RBAC pages without depending on live Entra.
- [x] Step 6: Enable nonce-backed strict script CSP by default and keep nonce handling aligned with the enforced policy.
- [x] Step 7: Remove the legacy CSP report path and make request nonce generation unconditional when CSP is enabled.
- [x] Step 8: Run cross-browser compatibility validation for the stricter CSP and scheduler/editor flows.

## Progress Notes

- 2026-03-19: Plan recorded. Step 1 is starting first because URL/config consolidation affects edge validation, test tooling, and script bootstrap assumptions together.
- 2026-03-19: Step 1 completed. `BASE_URL`, `PLAYWRIGHT_BASE_URL`, `SERVER__APPLICATION_ROOT`, the `#app-root` data island, and the scheduler editor path-prefix logic were removed in favor of a root-only deployment model and `TEST_BASE_URL` for higher-level test tooling.
- 2026-03-19: Step 2 completed. The production edge-check target now derives from `ENTRA__REDIRECT_URI`, startup rejects non-root callback URLs, and host-mode startup now stops immediately when the final served headers are wrong.
- 2026-03-19: Step 3 completed. CSP reports now land at `/csp-report`, are redacted before persistence, are stored in the database, and show up in the Admin Panel.
- 2026-03-19: Step 4 completed. Static asset URLs now receive a deploy-scoped `?v=` derived from `STATIC_ASSET_VERSION` or the git SHA, which reduces stale HTML/asset mismatches after deploys.
- 2026-03-19: Step 5 completed. Chromium smoke coverage now exercises the auth callback, template editor, and RBAC pages for baseline CSP and runtime/console failures.
- 2026-03-19: Step 6 completed. Default CSP now enforces nonce-backed strict script loading, and rendered templates attach the same request nonce to all script tags, including JSON data islands.
- 2026-03-19: Step 7 completed. CSP reporting now uses `report-to csp-endpoint` plus `Reporting-Endpoints`, the legacy `application/csp-report` ingest path was removed, and request nonces are generated whenever CSP is enabled.
- 2026-03-19: Step 8 started. Running Firefox and WebKit against the CSP/header smokes plus representative scheduler, template, and subroute interaction specs to verify the stricter policy does not break supported browsers.
- 2026-03-19: Step 8 completed. The targeted Firefox/WebKit CSP/header and scheduler/template subset passed first, then the full CI-safe Firefox/WebKit integration suite passed (`156 passed`, `8 skipped`). The only issue surfaced was a Firefox timing-sensitive assertion around the scheduler jump form's debounced history update, so the test now polls for the URL change instead of relying on a fixed sleep.

## Improvements Completed In This Pass

1. Added an nginx service to the compose stack that proxies host traffic on `APP_PORT` to the internal Flask container.
2. Enabled `ProxyFix` trust for one nginx hop in the compose scheduler service with explicit forwarded-for, proto, and host trust counts.
3. Added a minimal `<noscript>` fallback on the device schedule page so CSP or JS failures do not leave users with only an empty placeholder grid.
4. Removed the remaining inline swatch `<style>` block and moved swatch color application to the scheduler editor runtime, which lets the default CSP use `style-src 'self'` without a built-in nonce requirement.
5. Added route-level proxy reconstruction coverage for forwarded scheme, host, and port, including HSTS/CSP assertions on proxied-secure requests.
6. Added final-edge header verification in both Playwright (`tests/playwright/integration/security-headers.spec.ts`) and a standalone smoke checker (`scripts/check-edge-security-headers.py`) so the final served response is checked for a single active CSP authority.
7. Added a DB-backed `/csp-report` sink with redaction and an Admin Panel view for recent CSP violations.
8. Added deploy-scoped static asset versioning so top-level CSS and JS asset URLs are cache-busted by deploy/version rather than relying on unversioned HTML.
9. Tightened the default script policy to nonce-backed strict mode and added regression coverage that the rendered `<script>` tags carry the same nonce the header advertises.
10. Switched CSP reporting to Reporting API headers and removed the legacy `csp-report` payload path.

## Remaining Improvements

### 1. Real Deployment Gate

Priority: high

- Run `scripts/check-edge-security-headers.py` from the real deployment environment that can reach the final externally served URL.
- Fail deployment immediately if the final edge exposes duplicate CSP authorities, wrong HSTS behavior, or unsubstituted placeholders.
- Keep the current host-mode startup gate, but do not treat it as a substitute for a real edge-reachable post-deploy check.

Reason:
- The app and local proxy path are now checked well, but the final CDN/LB/proxy path can still drift independently.

### 2. CSP Report Review And Retention

Priority: medium

- Decide how long CSP reports should be retained, whether they need sampling, and whether admin filtering/export is worthwhile.

Reason:
- Violation capture exists now, but review and operational handling are still minimal.

### 3. Live-Auth And Environment-Specific Browser Coverage

Priority: medium

- Keep the CI-safe Firefox/WebKit sweep in place for browser compatibility, and use the live-auth or live-incident suites when real Entra or environment-specific behavior must be verified.
- Add more browser-specific coverage only if support expands beyond Chromium, Firefox, and WebKit or if a real auth/provider difference appears.

Reason:
- The browser-level CSP compatibility gap is materially smaller now; the remaining uncertainty is mostly live-auth and environment-specific behavior that mock-auth CI does not exercise.

### 4. Finer-Grained Asset Fingerprinting

Priority: low

- Keep the current deploy-scoped `?v=` strategy unless coarse cache busting proves insufficient.
- Only move to per-file fingerprinted filenames and a manifest pipeline if deploy experience shows a real need.

Reason:
- The current coarse versioning is intentionally low-maintenance and is probably enough unless deployments prove otherwise.

## Suggested Order

1. Make final-edge header verification a required post-deploy gate.
2. Decide how CSP reports should be retained and reviewed operationally.
3. Use live-auth or live-incident browser coverage only where real environment behavior matters.
4. Revisit per-file asset fingerprinting only if deploy-scoped cache busting proves too coarse.
