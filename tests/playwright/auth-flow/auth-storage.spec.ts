// Generates a Playwright storage state file for authenticated sessions.
import { test } from '@playwright/test';
import { signInWithCredentials } from '../utils/entra-login';
import { waitForAppShell } from '../utils/test-helpers';

const storageStatePath = process.env.PLAYWRIGHT_STORAGE_STATE;
const username = process.env.OAUTH_TEST_USERNAME ?? '';
const password = process.env.OAUTH_TEST_PASSWORD ?? '';
const isRealAuthMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'entra';

const hasCreds = Boolean(username && password);

test.describe('Generate storage state', () => {
  test('create storage state via real Entra login', async ({ page }, testInfo) => {
    if (!isRealAuthMode) {
      testInfo.skip('PLAYWRIGHT_AUTH_MODE=entra is required for real auth flow tests.');
      return;
    }
    if (!storageStatePath) {
      testInfo.skip('PLAYWRIGHT_STORAGE_STATE not set');
      return;
    }
    if (!hasCreds) {
      testInfo.skip('OAUTH_TEST_USERNAME/OAUTH_TEST_PASSWORD not set');
      return;
    }

    await page.goto('/auth/login');
    await signInWithCredentials(page, username, password);
    await waitForAppShell(page);

    await page.context().storageState({ path: storageStatePath });
  });
});
