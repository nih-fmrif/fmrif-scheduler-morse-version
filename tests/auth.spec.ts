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
    await loginPage.verifyPageElements();
  });

  test('should show superuser mode indicator when enabled', async () => {
    // In superuser mode, verify the indicator is visible
    if (process.env.RBAC__SUPERUSER_MODE !== 'true') {
      test.skip();
    }

    await loginPage.page.goto('/');
    await expect(loginPage.page.getByText(/logged in as superuser/i)).toBeVisible();
  });
});
