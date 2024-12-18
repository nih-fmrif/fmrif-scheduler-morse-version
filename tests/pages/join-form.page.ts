import { Page, Locator, expect } from '@playwright/test';

export class JoinFormPage {
  readonly page: Page;
  readonly joinFormLink: Locator;
  readonly homeLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.joinFormLink = page.getByRole('link', { name: 'join form' });
    this.homeLink = page.getByRole('link', { name: 'home' });
  }

  async goto() {
    await this.page.goto('/join');
  }

  async verifyPageElements() {
    await expect(this.page.getByText('home join form logged in as')).toBeVisible();
  }
}
