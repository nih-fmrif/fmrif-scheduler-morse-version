import type { Page } from '@playwright/test';

import { test, expect } from '../support/auth-fixture';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';
const sharedSecret = process.env.AUTH_TEST__SHARED_SECRET;

async function ensureProfileSession(
  page: Page,
  profile: 'admin' | 'member' | 'inactive',
  username: string
) {
  if (!sharedSecret) {
    throw new Error('AUTH_TEST__SHARED_SECRET must be set for mock RBAC coverage tests.');
  }

  const response = await page.request.post('/auth/test/session', {
    headers: {
      'X-Test-Auth-Secret': sharedSecret,
      'Content-Type': 'application/json',
    },
    data: { profile },
  });

  expect(response.ok()).toBeTruthy();
  await page.goto('/');
  await expect(page.locator('#user-menu-toggle')).toContainText(new RegExp(username, 'i'));
}

test.describe('Mock Role Coverage', () => {
  test.skip(!isMockMode, 'Mock role coverage only runs when PLAYWRIGHT_AUTH_MODE=mock');

  test.describe('admin profile', () => {
    test.use({ authProfile: 'admin' });

    test('should access consolidated RBAC admin pages', async ({ page }) => {
      await ensureProfileSession(page, 'admin', 'test-admin');

      await page.goto('/rbac');
      await expect(page).toHaveURL(/\/rbac$/);
      await expect(page.getByRole('heading', { name: /rbac explorer/i })).toBeVisible();

      await page.goto('/app/issues');
      await expect(page).toHaveURL(/\/app\/issues$/);
      await expect(page.getByRole('heading', { name: /potential issues/i })).toBeVisible();
    });
  });

  test.describe('member profile', () => {
    test.use({ authProfile: 'member' });

    test('should be denied on consolidated admin RBAC pages', async ({ page }) => {
      await ensureProfileSession(page, 'member', 'test-member');

      await page.goto('/rbac');
      await expect(page.getByRole('heading', { name: /access denied/i })).toBeVisible();

      await page.goto('/app/issues');
      await expect(page.getByRole('heading', { name: /access denied/i })).toBeVisible();
    });
  });

  test.describe('inactive profile', () => {
    test.use({ authProfile: 'inactive' });

    test('should be denied on active-user routes', async ({ page }) => {
      await ensureProfileSession(page, 'inactive', 'test-inactive');

      await page.goto('/groups');
      await expect(page.getByRole('heading', { name: /access denied/i })).toBeVisible();
      await expect(page.getByText(/do not have permission to view this page/i)).toBeVisible();
    });
  });
});
