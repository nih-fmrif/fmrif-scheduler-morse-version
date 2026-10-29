import { test, expect } from '../support/auth-fixture';
import { ensureProfileSession } from '../utils/mock-rbac-session';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('Mock Role Coverage (Access)', () => {
  test.skip(!isMockMode, 'Mock role coverage only runs when PLAYWRIGHT_AUTH_MODE=mock');

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

      await page.goto('/rbac');
      await expect(page.getByRole('heading', { name: /access denied/i })).toBeVisible();
      await expect(page.getByText(/do not have permission to view this page/i)).toBeVisible();
    });
  });
});
