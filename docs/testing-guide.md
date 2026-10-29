# Testing Guide (Local + CI)

Use [`testing-strategy.md`](testing-strategy.md) as the source of truth for:

- suite taxonomy (`unit`, `route`, `integration`, `auth-flow`, `live-incident`)
- where to place new tests
- environment prerequisites for each suite
- migration rules for moving test artifacts down the stack

For local execution, run:

```bash
AUTH_TEST__ENABLED=true AUTH_TEST__SHARED_SECRET=local-test-secret pixi run test-unit
AUTH_TEST__ENABLED=true AUTH_TEST__SHARED_SECRET=local-test-secret pixi run test-routes
AUTH_TEST__ENABLED=true AUTH_TEST__SHARED_SECRET=local-test-secret pixi run test-integration
```

Frontend helpers:

- `pixi run install-playwright`
- `pixi run test-integration`
- `pixi run test-integration-headed`
- `pixi run test-integration-ci`
