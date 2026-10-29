import { Page, Locator, expect } from '@playwright/test';

export class GroupEditPage {
  readonly page: Page;
  readonly saveButton: Locator;
  readonly createButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.saveButton = page.getByRole('button', { name: 'save' });
    this.createButton = page.getByRole('button', { name: 'create' });
  }

  async verifyEditForm() {
    await expect(this.page.locator('div').filter({ hasText: 'label, short label, long' })).toBeVisible();
  }

  async verifyAddForm() {
    await expect(this.page.locator('div').filter({ hasText: 'deptcode label, short label,' })).toBeVisible();
  }
}
