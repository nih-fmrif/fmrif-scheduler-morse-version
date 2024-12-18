import { Page, Locator, expect } from '@playwright/test';

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
  }

  async verifyPageElements() {
    await expect(this.page.getByText('home devices logged in as')).toBeVisible();
    await expect(this.page.getByText('show which devices active')).toBeVisible();
    await expect(this.page.getByLabel('Devices', { exact: true })).toBeVisible();
  }
}
