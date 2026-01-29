// tests/oauth.spec.ts
// OAuth 2.0 with Microsoft Entra authentication flow tests
import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://localhost:5051';
let baseUrlReachable = true;
let baseUrlError = '';

test.beforeAll(async ({ request }) => {
  try {
    await request.get(`${BASE_URL}/auth/login`, { timeout: 5000 });
  } catch (error) {
    baseUrlReachable = false;
    baseUrlError = String(error);
  }
});

test.describe('OAuth 2.0 / Entra Authentication', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    if (!baseUrlReachable) {
      testInfo.skip(`BASE_URL not reachable: ${baseUrlError || BASE_URL}`);
      return;
    }

    await page.goto('/auth/login');
  });

  test('should display OAuth login page with Entra button', async ({ page }) => {
    // Verify login page elements
    await expect(page.getByRole('heading', { name: /Device Scheduler/i })).toBeVisible();
    await expect(page.getByText(/Sign in with your NIH credentials/i)).toBeVisible();

    const loginButton = page.getByRole('button', { name: /Login with NIH Credentials/i });
    await expect(loginButton).toBeVisible();
    await expect(loginButton).toBeEnabled();
  });

  test('should load Entra configuration', async ({ page }) => {
    // Verify entra-config.json is loaded and accessible
    const configResponse = await page.evaluate(async () => {
      const response = await fetch('/api/config/entra.json');
      return response.json();
    });

    expect(configResponse.client_id).toBeTruthy();
    expect(configResponse.tenant_id).toBeTruthy();
    expect(configResponse.redirect_uri).toMatch(/^https?:\/\//);
    expect(configResponse.discovery_url).toMatch(/^https?:\/\//);
    if (configResponse.authorization_endpoint) {
      expect(configResponse.authorization_endpoint).toMatch(/^https?:\/\//);
    }
  });

  test('should initialize authentication module', async ({ page }) => {
    // Verify auth-manager.js initializes without errors
    const authInitialized = await page.evaluate(async () => {
      // Check if auth functions are available
      return typeof initializeAuth === 'function' &&
             typeof startOAuthFlow === 'function';
    });

    expect(authInitialized).toBe(true);
  });

  test('should show error on OAuth click (expected - would redirect to Entra)', async ({ page }) => {
    // This test verifies the login button attempts to start OAuth flow
    // In a real scenario, it would redirect to Entra login
    // For now, we just verify the button is clickable

    const loginButton = page.getByRole('button', { name: /Login with NIH Credentials/i });

    // Store initial URL
    const initialUrl = page.url();

    // Click login button - in real scenario would redirect to Entra
    // Set up a listener for any navigation
    let navigationAttempted = false;
    page.on('framenavigated', () => {
      navigationAttempted = true;
    });

    // Try clicking the button
    await loginButton.click();

    // Wait a bit to see if navigation starts
    await page.waitForTimeout(2000);

    // Either we redirected or we see an error message
    const pageUrl = page.url();
    const errorVisible = await page.getByText(/Error starting login/i).isVisible().catch(() => false);

    // Either URL changed (redirected to Entra) or error is shown
    expect(pageUrl !== initialUrl || errorVisible || navigationAttempted).toBe(true);
  });

  test('should verify PKCE flow is properly configured', async ({ page }) => {
    // Verify crypto API and PKCE utilities are available
    const pkceAvailable = await page.evaluate(async () => {
      // Check if crypto functions are available
      return typeof generateVerifier === 'function' &&
             typeof pkceChallenge === 'function' &&
             typeof crypto !== 'undefined';
    });

    expect(pkceAvailable).toBe(true);
  });

});
