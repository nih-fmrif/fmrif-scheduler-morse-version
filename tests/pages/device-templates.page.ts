import { Page, Locator, expect } from '@playwright/test';

export class DeviceTemplatesPage {
  readonly page: Page;
  readonly applyLink: Locator;
  readonly activeLink: Locator;
  readonly inactiveLink: Locator;
  readonly addTemplateLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.applyLink = page.getByRole('link', { name: 'apply' });
    this.activeLink = page.getByRole('link', { name: 'active', exact: true });
    this.inactiveLink = page.getByRole('link', { name: 'inactive' });
    this.addTemplateLink = page.getByRole('link', { name: 'add template' });
  }

  async verifyPageElements() {
    await expect(this.page.getByText('templates apply active')).toBeVisible();
  }
}
