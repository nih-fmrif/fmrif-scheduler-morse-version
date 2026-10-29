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
  await expect(page.getByText(new RegExp(`logged in as ${username}`, 'i'))).toBeVisible();
}

test.describe('Mock Role Coverage', () => {
  test.skip(!isMockMode, 'Mock role coverage only runs when PLAYWRIGHT_AUTH_MODE=mock');

  test.describe('admin profile', () => {
    test.use({ authProfile: 'admin' });

    test('should access inactive groups and devices pages', async ({ page }) => {
      await ensureProfileSession(page, 'admin', 'test-admin');

      await page.goto('/groups/inactive');
      await expect(page).toHaveURL(/\/groups\/inactive$/);
      await expect(page.locator('article.list-with-description')).toBeVisible();

      await page.goto('/devices/inactive');
      await expect(page).toHaveURL(/\/devices\/inactive$/);
      await expect(page.locator('article.list-with-description')).toBeVisible();
    });
  });

  test.describe('member profile', () => {
    test.use({ authProfile: 'member' });

    test('should be denied on group creation page', async ({ page }) => {
      await ensureProfileSession(page, 'member', 'test-member');

      await page.goto('/groups/add');
      await expect(page.getByText(/access denied/i)).toBeVisible();
    });

    test('should be denied on inactive-only routes', async ({ page }) => {
      await ensureProfileSession(page, 'member', 'test-member');

      await page.goto('/groups/inactive');
      await expect(page.getByText(/403 - access denied/i)).toBeVisible();

      await page.goto('/devices/inactive');
      await expect(page.getByText(/403 - access denied/i)).toBeVisible();
    });
  });

  test.describe('inactive profile', () => {
    test.use({ authProfile: 'inactive' });

    test('should be denied on active-user routes', async ({ page }) => {
      await ensureProfileSession(page, 'inactive', 'test-inactive');

      await page.goto('/groups');
      await expect(page.getByText(/limited to active users/i)).toBeVisible();
    });
  });
});
