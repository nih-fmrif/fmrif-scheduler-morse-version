import { test, expect } from '../support/auth-fixture';
import { waitForAppShell } from '../utils/test-helpers';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('RBAC Explorer', () => {
  test.skip(!isMockMode, 'RBAC explorer dropdown assertions require mock fixtures.');

  test.describe('admin profile', () => {
    test.use({ authProfile: 'admin' });

    test('keeps inline entity picker and matrix editor usable after detail-only payloads', async ({ page }) => {
      await page.goto('/rbac?scope=group');
      await waitForAppShell(page);

      const entitySearch = page.locator('#rbac-entity-search');
      const selectedEntityInput = page.locator('#rbac-entity');
      await expect(entitySearch).toBeVisible();

      await expect
        .poll(
          () =>
            selectedEntityInput.evaluate(
              (node) => (node as HTMLInputElement).value
            ),
          { timeout: 30000 }
        )
        .not.toBe('');

      const currentValue = await selectedEntityInput.evaluate(
        (node) => (node as HTMLInputElement).value
      );

      const entitiesResponse = await page.request.get(
        '/json/v1/rbac/explorer?scope=group&entities=1&detail=0'
      );
      expect(entitiesResponse.ok()).toBeTruthy();
      const entitiesPayload = await entitiesResponse.json();
      expect(Array.isArray(entitiesPayload.entities)).toBeTruthy();
      expect(entitiesPayload.entities.length).toBeGreaterThan(0);

      const detailResponse = await page.request.get(
        `/json/v1/rbac/explorer?scope=group&entity=${encodeURIComponent(
          currentValue
        )}&entities=0&detail=1`
      );
      expect(detailResponse.ok()).toBeTruthy();
      const detailPayload = await detailResponse.json();
      expect(detailPayload.entities).toEqual([]);
      expect(detailPayload.entities_included).toBe(false);

      const alternative = entitiesPayload.entities.find(
        (entity: { id: string; label: string }) => entity.id !== currentValue
      );
      if (!alternative) {
        return;
      }

      await entitySearch.click();
      await entitySearch.fill(alternative.id);
      await expect(
        page.locator(`#rbac-entity-list [data-entity-id="${alternative.id}"]`).first()
      ).toBeVisible();
      await entitySearch.press('Enter');

      await expect(page).toHaveURL(
        new RegExp(`[?&]entity=${encodeURIComponent(alternative.id)}(?:&|$)`),
        { timeout: 30000 }
      );

      await expect(selectedEntityInput).toHaveValue(alternative.id);
      await expect(entitySearch).toHaveValue(alternative.label);
      await expect(page.locator('#rbac-focus')).toContainText(/\S+/);
      await expect(page.locator('#rbac-matrices .rbac-matrix')).toHaveCount(2);
      await expect(page.locator('#rbac-audit-all-link')).toBeVisible();
      await expect(page.locator('#rbac-audit-list')).toHaveCount(1);
      await expect(page.locator('#rbac-audit-note')).toContainText(/RBAC|events|Showing/i);
    });
  });
});
