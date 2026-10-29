import { Page, Locator, expect } from '@playwright/test';
import { waitForAppShell } from '../utils/test-helpers';

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
    await waitForAppShell(this.page);
  }

  async verifyPageElements() {
    await waitForAppShell(this.page);
    await expect(this.page.getByRole('button', { name: 'submit' })).toBeVisible();
  }
}
