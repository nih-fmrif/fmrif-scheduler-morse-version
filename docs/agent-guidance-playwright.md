# Agent Guidance: Playwright

## Use Pixi tasks
- `pixi run install-js`
- `pixi run install-playwright`
- `pixi run test-integration`
- `pixi run test-integration-headed`
- `pixi run test-integration-ci`

## Scope requirements
Set a unique runtime scope before running integration tests:

```bash
export FMRIF_RUNTIME_SCOPE=<unique-scope>
```

Then use the wrapper flow:

```bash
bash setup-dotenv.sh
bash run-compose.sh --no-app
pixi run test-integration-ci
```

## Notes
- Integration wrappers pick isolated `APP_PORT` and `PLAYWRIGHT_BASE_URL` per scope/suite.
- Integration wrappers also isolate DB and Mailpit resources.
- If MCP browser/chrome-channel launch fails, use repository Playwright tooling via Pixi tasks.
