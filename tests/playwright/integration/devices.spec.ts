import { test, expect } from '../support/auth-fixture';
import { DevicesPage } from '../pages/devices.page';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('Devices Section', () => {
  test.skip(!isMockMode, 'Devices list fixture assertions only run in PLAYWRIGHT_AUTH_MODE=mock.');

  test('should render devices list views', async ({ page }) => {
    const devicesPage = new DevicesPage(page);

    await devicesPage.goto();
    await devicesPage.verifyPageElements();

    await devicesPage.activeDevicesLink.click();
    await expect(page).toHaveURL(/\/devices$/);
    await expect(page.locator('article.list-with-description')).toBeVisible();

    await devicesPage.inactiveDevicesLink.click();
    await expect(page).toHaveURL(/\/devices\/inactive$/);
    await expect(page.locator('article.list-with-description')).toBeVisible();
  });
});
