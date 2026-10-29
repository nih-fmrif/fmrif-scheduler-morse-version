// Server-side OAuth 2.0 / Entra authentication flow tests
import { test, expect, request } from '@playwright/test';
import { waitForAppShell } from '../utils/test-helpers';
import { signInWithCredentials } from '../utils/entra-login';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || process.env.BASE_URL || 'http://localhost:5051';
const storageStatePath = process.env.PLAYWRIGHT_STORAGE_STATE;
const hasCreds = Boolean(process.env.OAUTH_TEST_USERNAME && process.env.OAUTH_TEST_PASSWORD);
const isRealAuthMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'entra';

function shouldIgnoreHTTPSErrorsByDefault(urlString: string): boolean {
  try {
    const parsed = new URL(urlString);
    const isHttps = parsed.protocol === 'https:';
    const isLocalhost = parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1';
    return isHttps && !isLocalhost;
  } catch {
    return false;
  }
}

function parseBooleanEnv(name: string, fallback: boolean = false): boolean {
  const value = process.env[name];
  if (value === undefined) {
    return fallback;
  }
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
}

const ignoreHTTPSErrors = parseBooleanEnv(
  'PLAYWRIGHT_IGNORE_HTTPS_ERRORS',
  shouldIgnoreHTTPSErrorsByDefault(BASE_URL)
);
const proxyServer = (
  process.env.ALL_PROXY ||
  process.env.all_proxy ||
  process.env.PLAYWRIGHT_PROXY_SERVER ||
  process.env.HTTPS_PROXY ||
  process.env.https_proxy ||
  process.env.HTTP_PROXY ||
  process.env.http_proxy ||
  ''
).trim();
let baseUrlReachable = true;
let baseUrlError = '';

test.beforeAll(async () => {
  const probeClient = await request.newContext({
    baseURL: BASE_URL,
    ignoreHTTPSErrors,
    ...(proxyServer ? { proxy: { server: proxyServer } } : {}),
  });

  try {
    await probeClient.get('/auth/login', { timeout: 5000 });
  } catch (error) {
    baseUrlReachable = false;
    baseUrlError = String(error);
  } finally {
    await probeClient.dispose();
  }
});

test.describe('Login page basics', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    if (!baseUrlReachable) {
      testInfo.skip(`BASE_URL not reachable: ${baseUrlError || BASE_URL}`);
      return;
    }

    await page.goto('/auth/login');
  });

  test('should render login form that posts to server-side auth start', async ({ page }) => {
    const loginForm = page.locator('#login-content form');
    await expect(loginForm).toBeVisible();

    const action = await loginForm.getAttribute('action');
    expect(action).toContain('/auth/entra');
  });

  test('should not load client auth manager on login page', async ({ page }) => {
    const authManagerScript = page.locator('script[src*="auth-manager"]');
    await expect(authManagerScript).toHaveCount(0);

    const hasInitializeAuth = await page.evaluate(() => typeof (window as any).initializeAuth);
    expect(hasInitializeAuth).toBe('undefined');
  });
});

test.describe('Real Entra sign-in (credentials)', () => {
  test('should complete OAuth flow with credentials', async ({ page }, testInfo) => {
    if (!isRealAuthMode) {
      testInfo.skip('PLAYWRIGHT_AUTH_MODE=entra is required for real auth flow tests.');
      return;
    }
    if (!baseUrlReachable) {
      testInfo.skip(`BASE_URL not reachable: ${baseUrlError || BASE_URL}`);
      return;
    }
    if (!hasCreds) {
      testInfo.skip('OAUTH_TEST_USERNAME/OAUTH_TEST_PASSWORD not set');
      return;
    }
    if (storageStatePath) {
      testInfo.skip('PLAYWRIGHT_STORAGE_STATE set; use storage state test instead');
      return;
    }

    await page.goto('/auth/login');
    await signInWithCredentials(
      page,
      process.env.OAUTH_TEST_USERNAME ?? '',
      process.env.OAUTH_TEST_PASSWORD ?? '',
    );
    await waitForAppShell(page);
    await expect(page.getByText(/logged in as/i)).toBeVisible();
  });
});

test.describe('Real Entra sign-in (storage state)', () => {
  const storageConfig = storageStatePath ? { storageState: storageStatePath } : {};
  test.use(storageConfig);

  test('should access app with stored session', async ({ page }, testInfo) => {
    if (!isRealAuthMode) {
      testInfo.skip('PLAYWRIGHT_AUTH_MODE=entra is required for real auth flow tests.');
      return;
    }
    if (!storageStatePath) {
      testInfo.skip('PLAYWRIGHT_STORAGE_STATE not set');
      return;
    }
    if (!baseUrlReachable) {
      testInfo.skip(`BASE_URL not reachable: ${baseUrlError || BASE_URL}`);
      return;
    }

    await page.goto('/');
    await waitForAppShell(page);
    await expect(page.getByText(/logged in as/i)).toBeVisible();
  });
});
