import { test, expect } from '../support/auth-fixture';
import { waitForAppShell } from '../utils/test-helpers';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('Auth UI (Mock Profiles)', () => {
  test.skip(!isMockMode, 'Mock profile UI assertions only run in PLAYWRIGHT_AUTH_MODE=mock.');

  test.describe('admin profile', () => {
    test.use({ authProfile: 'admin' });

    test('should show admin shell navigation and redirect authenticated login page visits', async ({
      page,
    }) => {
      await page.goto('/');
      await waitForAppShell(page);
      await expect(page.locator('#user-menu-toggle')).toContainText(/test-admin/i);
      await expect(page.locator('[data-home-section="groups"]')).toBeVisible();
      await expect(page.locator('[data-home-section="groups"] a.list-card').first()).toBeVisible();
      await page.locator('#user-menu-toggle').click();
      await expect(page.locator('.user-menu-panel').getByRole('link', { name: 'join form' })).toBeVisible();
      await expect(page.locator('.user-menu-panel').getByRole('link', { name: 'email' })).toBeVisible();

      await page.goto('/auth/login');
      await expect(page).toHaveURL(/\/$/);
    });
  });

  test.describe('member profile', () => {
    test.use({ authProfile: 'member' });

    test('should hide admin navigation while keeping active-user links', async ({
      page,
    }) => {
      await page.goto('/');
      await waitForAppShell(page);
      await expect(page.locator('#user-menu-toggle')).toContainText(/test-member/i);
      await expect(page.locator('[data-home-section="groups"]')).toBeVisible();
      await page.locator('#user-menu-toggle').click();
      await expect(page.locator('.user-menu-panel').getByRole('link', { name: 'join form' })).toBeVisible();
      await expect(page.locator('.user-menu-panel').getByRole('link', { name: 'email' })).toBeVisible();

      await page.goto('/auth/login');
      await expect(page).toHaveURL(/\/$/);
    });
  });

  test.describe('inactive profile', () => {
    test.use({ authProfile: 'inactive' });

    test('should hide active-user links', async ({ page }) => {
      await page.goto('/');
      await waitForAppShell(page);
      await expect(page.locator('#user-menu-toggle')).toContainText(/test-inactive/i);
      await expect(page.locator('[data-home-section="groups"]')).toContainText(
        /Groups are available only to active users/i
      );
      await expect(page.locator('[data-home-section="groups"] a.list-card')).toHaveCount(0);
      await page.locator('#user-menu-toggle').click();
      await expect(page.locator('.user-menu-panel').getByRole('link', { name: 'join form' })).toHaveCount(0);
      await expect(page.locator('.user-menu-panel').getByRole('link', { name: 'email' })).toBeVisible();

      await page.goto('/auth/login');
      await expect(page).toHaveURL(/\/$/);
    });
  });
});
