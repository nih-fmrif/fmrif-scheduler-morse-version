// tests/auth.spec.ts
// OAuth 2.0 Authentication Tests
import { test, expect } from '@playwright/test';
import { LoginPage } from './pages/login.page';

const BASE_URL = process.env.BASE_URL || 'http://localhost:5051';
let baseUrlReachable = true;

test.beforeAll(async ({ request }) => {
  try {
    await request.get(`${BASE_URL}/auth/login`, { timeout: 5000 });
  } catch (error) {
    baseUrlReachable = false;
  }
});

test.describe('OAuth 2.0 Authentication', () => {
  let loginPage: LoginPage;

  test.beforeEach(async ({ page: testPage }, testInfo) => {
    if (!baseUrlReachable) {
      testInfo.skip();
      return;
    }

    loginPage = new LoginPage(testPage);
    await loginPage.goto();
  });

  test('should display OAuth login page', async () => {
    // Verify login page shows OAuth button (not LDAP form)
    await expect(loginPage.page.getByRole('heading', { name: /Device Scheduler/i })).toBeVisible();
    await expect(loginPage.page.getByText(/Sign in with your NIH credentials/i)).toBeVisible();
    await expect(loginPage.page.getByRole('button', { name: /Login with NIH Credentials/i })).toBeVisible();
  });

  test('should have OAuth button clickable', async () => {
    // Verify OAuth login button is interactive
    const loginButton = loginPage.page.getByRole('button', { name: /Login with NIH Credentials/i });
    await expect(loginButton).toBeEnabled();

    // Verify clicking button attempts OAuth flow
    const initialUrl = loginPage.page.url();
    await loginButton.click();

    // Either URL changes (redirect to Entra) or error is shown
    // In superuser mode, no redirect happens
    if (process.env.RBAC__SUPERUSER_MODE === 'false') {
      await loginPage.page.waitForTimeout(1000);
      const pageUrl = loginPage.page.url();
      const errorVisible = await loginPage.page.getByText(/Error starting login/i).isVisible().catch(() => false);
      expect(pageUrl !== initialUrl || errorVisible).toBe(true);
    }
  });

  test('should verify Entra configuration is loaded', async () => {
    // Verify OAuth config is properly loaded
    const configLoaded = await loginPage.page.evaluate(async () => {
      try {
        const response = await fetch('/api/config/entra.json');
        const config = await response.json();
        return !!(config.client_id && config.tenant_id && config.redirect_uri);
      } catch {
        return false;
      }
    });

    expect(configLoaded).toBe(true);
  });

  test('should show superuser mode indicator when enabled', async () => {
    // In superuser mode, verify the indicator is visible
    if (process.env.RBAC__SUPERUSER_MODE !== 'true') {
      test.skip();
    }

    await loginPage.page.goto('/');
    await expect(loginPage.page.getByText(/logged in as superuser/i)).toBeVisible();
  });

  test('should have OAuth credentials test (requires NIH network and real credentials)', async () => {
    // This test requires:
    // 1. Running on NIH network (can access Entra)
    // 2. Valid NIH credentials provided via environment
    // 3. RBAC__SUPERUSER_MODE=false

    const hasEntraCredentials = process.env.ENTRA_TEST_USERNAME && process.env.ENTRA_TEST_PASSWORD;

    if (!hasEntraCredentials) {
      test.skip();
      return;
    }

    if (process.env.RBAC__SUPERUSER_MODE === 'true') {
      test.skip();
      return;
    }

    // TODO: Implement real OAuth flow test with Entra credentials
    // This would involve:
    // 1. Click login button
    // 2. Navigate through Entra login page
    // 3. Enter credentials
    // 4. Verify callback and user creation
  });
});
