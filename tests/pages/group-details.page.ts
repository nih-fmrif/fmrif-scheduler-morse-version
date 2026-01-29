import { Page, Locator, expect } from '@playwright/test';
import { waitForAppShell } from '../utils/test-helpers';

export class GroupDetailsPage {
  readonly page: Page;
  readonly viewGroupLink: Locator;
  readonly membershipLink: Locator;
  readonly changePILink: Locator;
  readonly editLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.viewGroupLink = page.getByRole('link', { name: 'view Test' });
    this.membershipLink = page.getByRole('link', { name: 'membership for Test' });
    this.changePILink = page.getByRole('link', { name: 'change PI of Test' });
    this.editLink = page.getByRole('link', { name: 'edit Test' });
  }

  async verifyPageElements() {
    await waitForAppShell(this.page);
    await expect(this.page.getByRole('heading', { name: 'Test' })).toBeVisible();
    await expect(this.viewGroupLink).toBeVisible();
    await expect(this.membershipLink).toBeVisible();
    await expect(this.changePILink).toBeVisible();
    await expect(this.editLink).toBeVisible();
  }
}
