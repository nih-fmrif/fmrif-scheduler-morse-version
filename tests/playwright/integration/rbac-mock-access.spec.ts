import { test, expect } from '../support/auth-fixture';
import {
  ensureDevPiSession,
  ensureGroupPiSession,
  ensureProfileSession,
} from '../utils/mock-rbac-session';
import { waitForAppShell } from '../utils/test-helpers';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('Mock Role Coverage (Access)', () => {
  test.skip(!isMockMode, 'Mock role coverage only runs when PLAYWRIGHT_AUTH_MODE=mock');

  test.describe('member profile', () => {
    test.use({ authProfile: 'member' });

    test('should be denied on consolidated admin RBAC pages', async ({ page }, testInfo) => {
      await ensureProfileSession(page, 'member', 'test-member', { testInfo });

      await page.goto('/rbac');
      await expect(page.getByRole('heading', { name: /access denied/i })).toBeVisible();

      await page.goto('/app/issues');
      await expect(page.getByRole('heading', { name: /access denied/i })).toBeVisible();
    });
  });

  test.describe('inactive profile', () => {
    test.use({ authProfile: 'inactive' });

    test('should be denied on active-user routes', async ({ page }, testInfo) => {
      await ensureProfileSession(page, 'inactive', 'test-inactive', { testInfo });

      await page.goto('/rbac');
      await expect(page.getByRole('heading', { name: /access denied/i })).toBeVisible();
      await expect(page.getByText(/do not have permission to view this page/i)).toBeVisible();
    });
  });

  test.describe('group_pi_of_non_dev_group profile', () => {
    test.use({ authProfile: 'member' });

    test('should access RBAC but not RBAC audit panel', async ({ page }, testInfo) => {
      await ensureGroupPiSession(page, 'test-member', 'GPI', { testInfo });

      let auditRequestCount = 0;
      await page.route('**/json/v1/rbac/audit**', async (route) => {
        auditRequestCount += 1;
        await route.continue();
      });

      await page.goto('/rbac');
      await waitForAppShell(page);
      await expect(page.getByRole('heading', { name: /rbac explorer/i })).toBeVisible();
      await expect(page.getByRole('heading', { name: /RBAC Audit Log/i })).toHaveCount(0);
      await expect(page.locator('#rbac-audit-filters')).toHaveCount(0);
      await expect.poll(() => auditRequestCount).toBe(0);

      await page.goto('/app/issues');
      await expect(page.getByRole('heading', { name: /access denied/i })).toBeVisible();
    });
  });

  test.describe('dev_pi profile', () => {
    test.use({ authProfile: 'member' });

    test('should expose group+device scopes and hide audit panel', async ({ page }, testInfo) => {
      await ensureDevPiSession(page, 'test-member', { testInfo });

      let auditRequestCount = 0;
      await page.route('**/json/v1/rbac/audit**', async (route) => {
        auditRequestCount += 1;
        await route.continue();
      });

      const explorerResponse = await page.request.get(
        '/json/v1/rbac/explorer?scope=device&detail=0&active=1'
      );
      expect(explorerResponse.ok()).toBeTruthy();
      const payload = await explorerResponse.json();
      expect(payload.scope).toBe('device');
      expect(new Set(payload.scopes.map((scope: { id: string }) => scope.id))).toEqual(
        new Set(['group', 'device'])
      );

      await page.goto('/rbac?scope=device');
      await waitForAppShell(page);
      await expect(page.getByRole('heading', { name: /rbac explorer/i })).toBeVisible();
      await expect(page.getByRole('heading', { name: /RBAC Audit Log/i })).toHaveCount(0);
      await expect(page.locator('#rbac-audit-filters')).toHaveCount(0);
      await expect.poll(() => auditRequestCount).toBe(0);
    });
  });
});
