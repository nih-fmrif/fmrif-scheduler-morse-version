import type { Page, TestInfo } from '@playwright/test';

import { signInWithCredentials } from '../utils/entra-login';
import { waitForAppShell } from '../utils/test-helpers';

const AUTH_MODE = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase();

async function appShellVisible(page: Page): Promise<boolean> {
  try {
    await page.locator('nav.breadcrumb').waitFor({ state: 'visible', timeout: 4000 });
    await page.locator('section.login-info').waitFor({ state: 'visible', timeout: 4000 });
    return true;
  } catch {
    return false;
  }
}

async function ensureMockSession(page: Page, profile: string): Promise<void> {
  const sharedSecret = process.env.AUTH_TEST__SHARED_SECRET;
  if (!sharedSecret) {
    throw new Error('AUTH_TEST__SHARED_SECRET must be set for PLAYWRIGHT_AUTH_MODE=mock');
  }

  const response = await page.request.post('/auth/test/session', {
    headers: {
      'X-Test-Auth-Secret': sharedSecret,
      'Content-Type': 'application/json',
    },
    data: { profile },
  });

  if (!response.ok()) {
    const body = await response.text();
    throw new Error(`Failed to establish mock test session (${response.status()}): ${body}`);
  }

  // Confirm the browser context picked up the session cookie before route-specific navigation.
  await page.goto('/');
  if (!(await appShellVisible(page))) {
    throw new Error('Mock auth session was created, but the app shell was not visible.');
  }
}

async function ensureRealAuthSession(page: Page, testInfo: TestInfo, profile: string): Promise<void> {
  if (profile !== 'admin') {
    testInfo.skip('Non-admin profile switching is only supported in mock auth mode.');
    return;
  }

  await page.goto('/');
  if (await appShellVisible(page)) {
    return;
  }

  const loginButton = page.getByRole('button', { name: /Login with NIH Credentials/i });
  const loginVisible = await loginButton.isVisible({ timeout: 5000 }).catch(() => false);
  if (!loginVisible) {
    throw new Error('Expected either an authenticated app shell or the login page.');
  }

  const username = process.env.OAUTH_TEST_USERNAME ?? '';
  const password = process.env.OAUTH_TEST_PASSWORD ?? '';
  if (!username || !password) {
    testInfo.skip(
      'Set OAUTH_TEST_USERNAME/OAUTH_TEST_PASSWORD or provide PLAYWRIGHT_STORAGE_STATE for auth-flow runs.'
    );
    return;
  }

  await signInWithCredentials(page, username, password);
  await waitForAppShell(page);
}

export async function ensureAuthenticated(
  page: Page,
  testInfo: TestInfo,
  profile: string = 'admin'
): Promise<void> {
  if (AUTH_MODE === 'mock') {
    await ensureMockSession(page, profile);
    return;
  }

  if (AUTH_MODE === 'entra') {
    await ensureRealAuthSession(page, testInfo, profile);
    return;
  }

  testInfo.skip(`Unsupported PLAYWRIGHT_AUTH_MODE=${AUTH_MODE}`);
}
