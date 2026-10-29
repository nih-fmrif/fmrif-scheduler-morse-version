Live-incident Playwright tests belong in this directory.

Rules:
- Keep each test focused on a single incident and a single assertion theme.
- Add a header comment with incident ID/date and why it cannot be covered by unit/integration tests.
- Use resilient assertions that tolerate normal production data churn.
- Do not run these tests in CI by default.
