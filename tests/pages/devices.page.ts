import { Page, Locator, expect } from '@playwright/test';
import { waitForAppShell } from '../utils/test-helpers';

export class DevicesPage {
  readonly page: Page;
  readonly devicesLink: Locator;
  readonly activeDevicesLink: Locator;
  readonly inactiveDevicesLink: Locator;
  readonly addDeviceLink: Locator;
  readonly testScannerLink: Locator;
  readonly homeLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.devicesLink = page.getByRole('link', { name: 'devices', exact: true });
    this.activeDevicesLink = page.getByRole('link', { name: 'active devices', exact: true });
    this.inactiveDevicesLink = page.getByRole('link', { name: 'inactive devices' });
    this.addDeviceLink = page.getByRole('link', { name: 'add device' });
    this.testScannerLink = page.getByRole('link', { name: 'Test Scanner' });
    this.homeLink = page.getByRole('link', { name: 'home' });
  }

  async goto() {
    await this.page.goto('/devices');
    await waitForAppShell(this.page);
  }

  async verifyPageElements() {
    await waitForAppShell(this.page);
    await expect(this.devicesLink).toBeVisible();
    await expect(this.activeDevicesLink).toBeVisible();
    await expect(this.inactiveDevicesLink).toBeVisible();
    await expect(this.addDeviceLink).toBeVisible();
    await expect(this.page.locator('article.list-with-description')).toBeVisible();
  }
}
