import { test, expect } from '../support/auth-fixture';
import { waitForAppShell } from '../utils/test-helpers';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('RBAC Explorer', () => {
  test.skip(!isMockMode, 'RBAC explorer dropdown assertions require mock fixtures.');

  test.describe('admin profile', () => {
    test.use({ authProfile: 'admin' });

    test('requests audit once during initial entities+detail bootstrap', async ({ page }) => {
      let auditRequestCount = 0;
      await page.route('**/json/v1/rbac/audit**', async (route) => {
        auditRequestCount += 1;
        await route.continue();
      });

      await page.goto('/rbac?scope=group');
      await waitForAppShell(page);
      await expect(page.locator('#rbac-focus')).toContainText(/\S+/);
      await page.waitForLoadState('networkidle');

      await expect.poll(() => auditRequestCount).toBe(1);
      await expect(page.locator('#rbac-audit-list')).toBeVisible();
      await expect(page.locator('#rbac-audit-note')).toContainText(/RBAC|events|Showing/i);
    });

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
      const matrixCount = await page.locator('#rbac-matrices .rbac-matrix').count();
      expect(matrixCount).toBeGreaterThanOrEqual(2);
      await expect(page.locator('#rbac-audit-list')).toHaveCount(1);
      await expect(page.locator('#rbac-audit-note')).toContainText(/RBAC|events|Showing/i);
    });

    test('filters matrices by the scoped column with explicit placeholder text', async ({ page }) => {
      const syntheticTargetToken = 'synthetic-rbac-target-state';
      let patchedMatrixId = '';
      let patchedDetailPayload = false;

      await page.route('**/json/v1/rbac/explorer**', async (route) => {
        const requestUrl = new URL(route.request().url());
        const isDetailRequest =
          requestUrl.searchParams.get('detail') === '1' &&
          requestUrl.searchParams.get('entities') === '0';
        if (!isDetailRequest || patchedDetailPayload) {
          await route.continue();
          return;
        }

        const response = await route.fetch();
        const payload = await response.json();
        const detail =
          payload && typeof payload === 'object' ? payload.detail : null;
        const matrices =
          detail && typeof detail === 'object' && Array.isArray((detail as { matrices?: unknown[] }).matrices)
            ? ((detail as { matrices: unknown[] }).matrices as Array<Record<string, unknown>>)
            : [];
        const matrix = matrices.find(
          (candidate: { rows?: unknown[]; filter?: unknown; columns?: unknown[] }) =>
            candidate.filter !== false &&
            Array.isArray(candidate.columns) &&
            candidate.columns.length >= 2 &&
            typeof (candidate.columns[0] as { key?: unknown })?.key === 'string' &&
            typeof (candidate.columns[1] as { key?: unknown })?.key === 'string' &&
            Array.isArray(candidate.rows) &&
            candidate.rows.length > 0
        );

        if (
          matrix &&
          Array.isArray(matrix.columns) &&
          matrix.columns.length >= 2 &&
          Array.isArray(matrix.rows) &&
          matrix.rows.length > 0
        ) {
          const primaryKey = String(
            (matrix.columns[0] as { key?: unknown }).key || ''
          );
          const secondaryKey = String(
            (matrix.columns[1] as { key?: unknown }).key || ''
          );
          const cloneRow = (
            source: Record<string, unknown>,
            token: string
          ): Record<string, unknown> => {
            const row = JSON.parse(JSON.stringify(source)) as Record<string, unknown>;

            const existingSearch =
              typeof row.search === 'string' ? row.search : '';
            row.search = `${existingSearch} ${token}`.trim();

            if (typeof row.id === 'string' && row.id.length > 0) {
              row.id = `${row.id}-${token}`;
            }
            if (typeof row.label === 'string' && row.label.length > 0) {
              row.label = `${row.label} ${token}`;
            }
            if (typeof row.field === 'string' && row.field.length > 0) {
              row.field = `${row.field}_${token.replace(/-/g, '_')}`;
            }
            if (row.cells && typeof row.cells === 'object') {
              const cells = row.cells as Record<string, unknown>;
              if (
                primaryKey !== '' &&
                Object.prototype.hasOwnProperty.call(cells, primaryKey)
              ) {
                cells[primaryKey] = `seed-${Date.now()}`;
              }
              if (
                secondaryKey !== '' &&
                Object.prototype.hasOwnProperty.call(cells, secondaryKey)
              ) {
                cells[secondaryKey] = token.toUpperCase();
              }
            }
            return row;
          };

          const seedRows = matrix.rows.map((row: unknown) =>
            JSON.parse(JSON.stringify(row))
          ) as Array<Record<string, unknown>>;

          while (matrix.rows.length < 9) {
            const seed = seedRows[matrix.rows.length % seedRows.length];
            matrix.rows.push(cloneRow(seed, `synthetic-rbac-fill-${matrix.rows.length + 1}`));
          }

          matrix.rows.unshift(cloneRow(seedRows[0], syntheticTargetToken));
          patchedMatrixId = String(matrix.id || '').trim();
          patchedDetailPayload = true;
        }

        await route.fulfill({ response, json: payload });
      });

      await page.goto('/rbac?scope=group');
      await waitForAppShell(page);
      await expect.poll(() => patchedDetailPayload).toBeTruthy();

      await expect(
        page.locator('article.rbac-matrix[data-matrix-id="group-membership-matrix"] .rbac-matrix-toolbar input[type="search"]')
      ).toHaveAttribute('placeholder', 'filter user');
      await expect(
        page.locator('article.rbac-matrix[data-matrix-id="group-device-links-matrix"] .rbac-matrix-toolbar input[type="search"]')
      ).toHaveAttribute('placeholder', 'filter device');

      const matrixBlock =
        patchedMatrixId !== ''
          ? page.locator(`article.rbac-matrix[data-matrix-id="${patchedMatrixId}"]`)
          : page.locator('article.rbac-matrix').first();
      await expect(matrixBlock).toBeVisible();

      const targetRowLocator = matrixBlock.locator(
        'tbody tr',
        { hasText: syntheticTargetToken.toUpperCase() }
      );
      await expect(targetRowLocator).toHaveCount(1);
      await expect(targetRowLocator).toHaveAttribute('data-hidden', '0');

      const rowFilter = matrixBlock.locator('.rbac-matrix-toolbar input[type="search"]');
      await expect(rowFilter).toBeVisible();
      await rowFilter.fill(syntheticTargetToken);

      await expect(targetRowLocator).toHaveAttribute('data-hidden', '1');
      await expect(targetRowLocator).not.toBeVisible();
    });
  });
});
