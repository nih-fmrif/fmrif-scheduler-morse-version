import { Page, Locator, expect } from '@playwright/test';
import { waitForAppShell } from '../utils/test-helpers';

export class ListActionFormPage {
  readonly page: Page;
  readonly listActionFormLink: Locator;
  readonly submitButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.listActionFormLink = page.getByRole('link', { name: 'list action form' });
    this.submitButton = page.getByRole('button', { name: 'submit' });
  }

  async goto() {
    await this.page.goto('/mailing-lists');
    await waitForAppShell(this.page);
  }

  async verifyPageElements() {
    await waitForAppShell(this.page);
    await expect(this.listActionFormLink).toBeVisible();
    await expect(this.page.locator('form.mailing-list-form')).toBeVisible();
    await expect(this.submitButton).toBeVisible();
  }

  async submitForm() {
    await this.submitButton.click();
  }
}
