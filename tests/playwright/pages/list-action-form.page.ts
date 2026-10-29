import { Page, Locator, expect } from '@playwright/test';
import { waitForAppShell } from '../utils/test-helpers';

export class ListActionFormPage {
  readonly page: Page;
  readonly emailLink: Locator;
  readonly userMenuToggle: Locator;
  readonly submitButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.emailLink = page.locator('.user-menu-panel').getByRole('link', { name: 'email' });
    this.userMenuToggle = page.locator('#user-menu-toggle');
    this.submitButton = page.getByRole('button', { name: 'submit' });
  }

  async goto() {
    await this.page.goto('/mailing-lists');
    await waitForAppShell(this.page);
  }

  async verifyPageElements() {
    await waitForAppShell(this.page);
    await this.userMenuToggle.click();
    await expect(this.page.locator('.user-menu[open]')).toBeVisible();
    await expect(this.emailLink).toBeVisible();
    await expect(this.page.locator('form.mailing-list-form')).toBeVisible();
    await expect(this.submitButton).toBeVisible();
  }

  async submitForm() {
    await this.submitButton.click();
  }
}
