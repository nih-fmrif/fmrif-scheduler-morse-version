import { Page, Locator, expect } from '@playwright/test';
import { waitForAppShell } from '../utils/test-helpers';

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
    await waitForAppShell(this.page);
    await expect(this.page.locator('div.body.device')).toBeVisible();
    await expect(this.page.locator('div.body.device nav.jump-form, div.body.device p.note')).toBeVisible();
    await expect(this.scheduleLink).toBeVisible();
    await expect(this.templatesLink).toBeVisible();
  }
}
