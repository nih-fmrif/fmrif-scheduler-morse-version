import { test, expect } from '@playwright/test';
import { DevicesPage } from './pages/devices.page';
import { DeviceDetailsPage } from './pages/device-details.page';
import { DeviceTemplatesPage } from './pages/device-templates.page';

test.describe('Devices Section', () => {
  let devicesPage: DevicesPage;
  let deviceDetailsPage: DeviceDetailsPage;
  let deviceTemplatesPage: DeviceTemplatesPage;

  test.beforeEach(async ({ page }) => {
    devicesPage = new DevicesPage(page);
    deviceDetailsPage = new DeviceDetailsPage(page);
    deviceTemplatesPage = new DeviceTemplatesPage(page);
  });

  test('should navigate through devices list', async () => {
    await devicesPage.goto();
    await devicesPage.verifyPageElements();
    await devicesPage.activeDevicesLink.click();
    await devicesPage.inactiveDevicesLink.click();
    await devicesPage.addDeviceLink.click();
  });

  test('should view device details', async ({ page }) => {
    await devicesPage.goto();
    await devicesPage.testScannerLink.click();
    await deviceDetailsPage.verifyPageElements();
    await deviceDetailsPage.scheduleLink.click();
    await deviceDetailsPage.templatesLink.click();
  });

  test('should manage device templates', async ({ page }) => {
    await devicesPage.goto();
    await devicesPage.testScannerLink.click();
    await deviceDetailsPage.templatesLink.click();
    await deviceTemplatesPage.verifyPageElements();
    await deviceTemplatesPage.applyLink.click();
    await deviceTemplatesPage.activeLink.click();
    await deviceTemplatesPage.inactiveLink.click();
    await deviceTemplatesPage.addTemplateLink.click();
    await expect(page.locator('div').filter({ hasText: 'clone prepopulate new' })).toBeVisible();
  });

  test('should add new device', async ({ page }) => {
    await devicesPage.goto();
    await devicesPage.addDeviceLink.click();
    await expect(page.locator('div').filter({ hasText: 'scannercode label description' })).toBeVisible();
    await page.getByRole('button', { name: 'create' }).click();
    await expect(page.getByLabel('scannercode')).toBeVisible();
  });
});
