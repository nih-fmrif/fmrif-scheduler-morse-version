// tests/auth-storage.spec.ts
// Generates a Playwright storage state file for authenticated sessions.
import { test } from '@playwright/test';
import { signInWithCredentials } from './utils/entra-login';

const storageStatePath = process.env.PLAYWRIGHT_STORAGE_STATE;
const username = process.env.OAUTH_TEST_USERNAME ?? '';
const password = process.env.OAUTH_TEST_PASSWORD ?? '';

const hasCreds = Boolean(username && password);

test.describe('Generate storage state', () => {
  test('create storage state via real Entra login', async ({ page }, testInfo) => {
    if (!storageStatePath) {
      testInfo.skip('PLAYWRIGHT_STORAGE_STATE not set');
      return;
    }
    if (!hasCreds) {
      testInfo.skip('OAUTH_TEST_USERNAME/OAUTH_TEST_PASSWORD not set');
      return;
    }
    if (process.env.RBAC__SUPERUSER_MODE === 'true') {
      testInfo.skip('RBAC__SUPERUSER_MODE=true bypasses auth flow');
      return;
    }

    await page.goto('/auth/login');
    await signInWithCredentials(page, username, password);

    await page.context().storageState({ path: storageStatePath });
  });
});
