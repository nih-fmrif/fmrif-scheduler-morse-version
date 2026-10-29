import { test, expect } from '../support/auth-fixture';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('Device Subroutes', () => {
  test.skip(!isMockMode, 'Device template subroute assertions require mock fixtures.');

  test('should navigate from devices list through template subroutes', async ({ page }) => {
    await page.goto('/devices');

    const deviceLink = page.locator('article.list-with-description ul li a').first();
    await expect(deviceLink).toBeVisible();

    const href = await deviceLink.getAttribute('href');
    expect(href).toMatch(/^\/device\/[^/]+$/);

    await deviceLink.click();
    await expect(page).toHaveURL(/\/device\/[^/?#]+(?:\?.*)?$/);

    const templatesLink = page.getByRole('link', { name: 'templates', exact: true });
    await expect(templatesLink).toBeVisible();
    await templatesLink.click();
    await expect(page).toHaveURL(/\/device\/[^/]+\/templates$/);

    await page.getByRole('link', { name: 'active', exact: true }).click();
    await expect(page).toHaveURL(/\/device\/[^/]+\/templates\/list$/);

    await page.getByRole('link', { name: 'inactive', exact: true }).click();
    await expect(page).toHaveURL(/\/device\/[^/]+\/templates\/archive$/);

    await page.getByRole('link', { name: 'apply', exact: true }).click();
    await expect(page).toHaveURL(/\/device\/[^/]+\/templates$/);
  });
});
