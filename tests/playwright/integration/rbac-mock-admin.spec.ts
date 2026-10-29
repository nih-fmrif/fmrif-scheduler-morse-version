import { test, expect } from '../support/auth-fixture';
import { ensureProfileSession } from '../utils/mock-rbac-session';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('Mock Role Coverage (Admin)', () => {
  test.skip(!isMockMode, 'Mock role coverage only runs when PLAYWRIGHT_AUTH_MODE=mock');
  test.use({ authProfile: 'admin' });

  test('should access consolidated RBAC admin pages', async ({ page }, testInfo) => {
    await ensureProfileSession(page, 'admin', 'test-admin', { testInfo });

    await page.goto('/rbac');
    await expect(page).toHaveURL(/\/rbac(?:\?|$)/);
    await expect(page.getByRole('heading', { name: /rbac explorer/i })).toBeVisible();

    await page.goto('/app/issues');
    expect(new URL(page.url()).pathname).toBe('/app/issues');
    await expect(page.getByRole('heading', { name: /potential issues/i })).toBeVisible();
  });

  test('updates admin audit filters in place without full page reload', async ({ page }, testInfo) => {
    await ensureProfileSession(page, 'admin', 'test-admin', { testInfo });

    await page.goto('/app/issues');
    await expect(page.getByRole('heading', { name: /potential issues/i })).toBeVisible();
    await page.waitForLoadState('networkidle');

    const pageMarker = await page.evaluate(() => {
      const marker = Math.random().toString(36).slice(2);
      window.__adminAuditPageMarker = marker;
      return marker;
    });

    await page.locator('#email-audit-search-field').selectOption('recipient');
    await page.locator('#email-audit-search').fill('listserv@example.com');
    await expect
      .poll(() => {
        const url = new URL(page.url());
        return `${url.searchParams.get('email_search_field')}|${url.searchParams.get('email_search')}`;
      })
      .toBe('recipient|listserv@example.com');

    const finalUrl = new URL(page.url());
    expect(finalUrl.pathname).toBe('/app/issues');
    expect(finalUrl.searchParams.get('email_search')).toBe('listserv@example.com');
    const markerAfterFilters = await page.evaluate(() => window.__adminAuditPageMarker);
    expect(markerAfterFilters).toBe(pageMarker);
  });

  test('runs notification detection scan and applies notification search filters', async ({
    page,
  }, testInfo) => {
    await ensureProfileSession(page, 'admin', 'test-admin', { testInfo });

    await page.goto('/app/issues');
    await expect(page.getByRole('heading', { name: /potential issues/i })).toBeVisible();

    await page.getByRole('button', { name: /run detection scan/i }).click();
    await expect(page).toHaveURL(/\/app\/issues/);

    await page.locator('#notification-search-field').selectOption('category');
    await expect(page.locator('#notification-search')).toHaveAttribute(
      'placeholder',
      'for example: top priority'
    );
    await page.locator('#notification-search').fill('top priority');
    await expect
      .poll(() => {
        const url = new URL(page.url());
        return `${url.searchParams.get('notification_search_field')}|${url.searchParams.get('notification_search')}|${url.searchParams.get('notification_include_open')}`;
      })
      .toBe('category|top priority|1');
  });

  test('applies RBAC matrix changes without a browser confirm dialog', async ({ page }, testInfo) => {
    await ensureProfileSession(page, 'admin', 'test-admin', { testInfo });

    const dialogs: string[] = [];
    page.on('dialog', (dialog) => {
      dialogs.push(dialog.message());
      void dialog.dismiss();
    });

    await page.goto('/rbac?scope=device&entity=d');
    await expect(page.getByRole('status')).toContainText('Relationships loaded.');

    const section = page.locator('article.rbac-matrix').filter({
      has: page.getByRole('heading', { name: 'DEV user permissions' }),
    });
    await expect(section).toBeVisible();

    const targetRow = section.locator('tbody tr').filter({ hasText: 'user0049' }).first();
    await expect(targetRow).toBeVisible();

    const checkbox = targetRow.locator('input[type="checkbox"]').nth(3);
    if (!(await checkbox.isChecked())) {
      await checkbox.check();
      await section.getByRole('button', { name: /apply permission updates/i }).click();
      await expect(page.locator('#app-feedback')).toContainText(
        /(RBAC updates applied|Applied \d+ of \d+ requested RBAC changes)/i
      );
    }

    expect(dialogs).toEqual([]);
  });

  test('shows modal required-field errors through app notifications', async ({ page }, testInfo) => {
    await ensureProfileSession(page, 'admin', 'test-admin', { testInfo });

    await page.goto('/rbac');
    await expect(page.getByRole('heading', { name: /rbac explorer/i })).toBeVisible();

    await page.getByRole('button', { name: /\+ add group/i }).click();
    await expect(page.locator('#rbac-modal')).toBeVisible();
    await page.locator('#rbac-modal-submit').click();

    await expect(page.locator('#app-feedback')).toContainText(/group id is required/i);
    await expect(page.locator('#rbac-modal')).toBeVisible();
  });
});
