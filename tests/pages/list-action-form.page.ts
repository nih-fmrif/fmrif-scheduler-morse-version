import { Page, Locator, expect } from '@playwright/test';

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
  }

  async verifyPageElements() {
    await expect(this.page.getByText('home list action form logged')).toBeVisible();
    await expect(this.page.getByText('email the NIH email address used for this list (must end in nih.gov) name your')).toBeVisible();
    await expect(this.listActionFormLink).toBeVisible();
  }

  async submitForm() {
    await this.submitButton.click();
  }
}
