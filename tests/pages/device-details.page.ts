import { Page, Locator, expect } from '@playwright/test';

export class DeviceDetailsPage {
  readonly page: Page;
  readonly scheduleLink: Locator;
  readonly templatesLink: Locator;
  readonly groupsLink: Locator;
  readonly usersLink: Locator;
  readonly editLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.scheduleLink = page.getByRole('link', { name: 'schedule' });
    this.templatesLink = page.getByRole('link', { name: 'templates' });
    this.groupsLink = page.getByRole('link', { name: 'groups' });
    this.usersLink = page.getByRole('link', { name: 'users' });
    this.editLink = page.getByRole('link', { name: 'edit {device.label}' });
  }

  async verifyPageElements() {
    await expect(this.page.getByText('show schedule templates')).toBeVisible();
  }
}
