import type { Page } from '@playwright/test';

import { test, expect } from '../support/auth-fixture';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';
const SEEDED_TEMPLATE_DEVICE = 'd';

async function gotoTemplateApplyPage(page: Page, deviceId = SEEDED_TEMPLATE_DEVICE) {
  await page.goto('/');

  const deviceLink = page.locator(`[data-home-section="devices"] a.list-card[href="/device/${deviceId}"]`);
  await expect(deviceLink).toBeVisible();

  await deviceLink.click();
  await expect(page).toHaveURL(new RegExp(`/device/${deviceId}(?:\\?.*)?$`));

  const templatesLink = page.getByRole('link', { name: 'templates', exact: true });
  await expect(templatesLink).toBeVisible();
  await templatesLink.click();
  await expect(page).toHaveURL(new RegExp(`/device/${deviceId}/templates$`));
  await expect(page.locator('.apply-helper')).toHaveClass(/js-loaded/);
}

async function pickTemplateCode(page: Page, projectName: string) {
  const projectPools: Record<string, string[]> = {
    chromium: ['X', 'U', 'V'],
    firefox: ['Y', 'W', 'Q'],
    webkit: ['Z', 'R', 'S'],
  };
  const candidates = [...(projectPools[projectName] ?? []), 'X', 'Y', 'Z', 'U', 'V', 'W', 'Q', 'R', 'S'];
  const existing = new Set(
    await page.locator('datalist option').evaluateAll((options) =>
      options.map((option) => (option as HTMLOptionElement).value)
    )
  );

  for (const candidate of candidates) {
    if (!existing.has(candidate)) {
      return candidate;
    }
  }

  throw new Error(`No free template code available for project ${projectName}.`);
}

async function createReadyTemplate(page: Page, projectName: string) {
  await page.goto(`/device/${SEEDED_TEMPLATE_DEVICE}/templates/add`);

  const templateId = await pickTemplateCode(page, projectName);
  await page.locator('input[name="id"]').fill(templateId);
  await page.locator('input[name="label"]').fill(`Ready smoke template ${templateId}`);
  await page.locator('textarea[name="description"]').fill(`Template smoke ${templateId}`);
  await page.getByRole('button', { name: 'create' }).click();

  await expect(page).toHaveURL(new RegExp(`/device/${SEEDED_TEMPLATE_DEVICE}/templates/edit/${templateId}$`));
  return templateId;
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

  test('should submit template application when confirm is pressed', async ({ page }, testInfo) => {
    let postCount = 0;
    let postBody = '';

    const templateCode = await createReadyTemplate(page, testInfo.project.name);

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
