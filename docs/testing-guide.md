# Testing Guide

## Test Environment

The project uses multiple test environments:

1. **Docker Environment**
   - Used by CI/CD pipeline
   - Configured via `.env`
   - PostgreSQL on port 5444
   - Entra authentication is handled via browser flow (no local auth service)
   - Application on port 5051

2. **Local Development Environment**
   - Used for local testing
   - Configured via `.env`
   - Connects to Docker services

## Running Tests

### Python Tests (pytest)

```bash
# Run all Python tests
pytest tests/python/

# Run with coverage
pytest --cov=scheduler tests/python/
```

### End-to-End Tests (Playwright)

```bash
# Run all E2E tests
BASE_URL=http://localhost:5051 RBAC__SUPERUSER_MODE=true npm run test

# Run with UI
npm run test:ui

# Run in headed mode i.e. the browser is visible
npm run test:headed
```

## Test Configuration

1. **pytest Configuration**
   - Configuration in `pytest.ini`
   - Test fixtures in `tests/python/conftest.py`
   - Database uses test-specific configuration

2. **Playwright Configuration**
   - Configuration in `playwright.config.ts`
   - Base URL: http://localhost:5051
   - Browser: Chromium
   - If `RBAC__SUPERUSER_MODE=false`, provide real Entra settings for auth-related tests

## Writing Tests

1. **Python Unit Tests**
   - Use pytest fixtures
   - Test individual components
   - Mock external services

2. **End-to-End Tests**
   - Use Page Object Model
   - Test user workflows
   - Verify UI components
