import type { Page } from '@playwright/test';

import { test, expect } from '../support/auth-fixture';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

async function gotoTemplateApplyPage(page: Page) {
  await page.goto('/');

  const deviceLink = page.locator('[data-home-section="devices"] a.list-card').first();
  await expect(deviceLink).toBeVisible();

  const href = await deviceLink.getAttribute('href');
  expect(href).toMatch(/^\/device\/[^/]+$/);

  await deviceLink.click();
  await expect(page).toHaveURL(/\/device\/[^/?#]+(?:\?.*)?$/);

  const templatesLink = page.getByRole('link', { name: 'templates', exact: true });
  await expect(templatesLink).toBeVisible();
  await templatesLink.click();
  await expect(page).toHaveURL(/\/device\/[^/]+\/templates$/);
}

async function firstReadyTemplateCode(page: Page) {
  const code = await page
    .locator('.apply-helper-js button[data-tc]:not([disabled])')
    .first()
    .getAttribute('data-tc');
  expect(code).toBeTruthy();
  return code!;
}

test.describe('Device Subroutes', () => {
  test.skip(!isMockMode, 'Device template subroute assertions require mock fixtures.');
  test.use({ authProfile: 'admin' });

  test('should navigate from devices list through template subroutes', async ({ page }) => {
    await gotoTemplateApplyPage(page);

    await page.getByRole('link', { name: 'active', exact: true }).click();
    await expect(page).toHaveURL(/\/device\/[^/]+\/templates\/list$/);

    await page.getByRole('link', { name: 'inactive', exact: true }).click();
    await expect(page).toHaveURL(/\/device\/[^/]+\/templates\/archive$/);

    await page.getByRole('link', { name: 'apply', exact: true }).click();
    await expect(page).toHaveURL(/\/device\/[^/]+\/templates$/);
  });

  test('should submit template application when confirm is pressed', async ({ page }) => {
    let postCount = 0;
    let postBody = '';

    await page.route('**/device/*/templates', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }

      postCount += 1;
      postBody = request.postData() ?? '';
      await route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<!doctype html><html><head><title>templates applied</title></head><body>templates applied</body></html>',
      });
    });

    await gotoTemplateApplyPage(page);
    const templateCode = await firstReadyTemplateCode(page);
    await page.locator('#templates').fill(templateCode);
    await page.locator('form.template-apply button[type="submit"]').click();

    const confirmDialog = page.locator('#confirm-dialog-container .dialog-box-container');
    await expect(confirmDialog).toBeVisible();
    await expect(confirmDialog).toContainText(/Are you sure/i);

    await page.locator('#confirm-dialog-container button[name="confirm"]').click();

    await expect.poll(() => postCount).toBe(1);
    expect(postBody).toContain(`templates=${templateCode}`);
    await expect(page.locator('body')).toContainText('templates applied');
  });
});
