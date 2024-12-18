import { Page, Locator, expect } from '@playwright/test';

export class HomePage {
  readonly page: Page;
  readonly homeLink: Locator;
  readonly devicesLink: Locator;
  readonly groupsLink: Locator;
  readonly joinFormLink: Locator;
  readonly listActionFormLink: Locator;
  readonly skipToMainContent: Locator;

  constructor(page: Page) {
    this.page = page;
    this.homeLink = page.getByRole('link', { name: 'home' });
    this.devicesLink = page.getByRole('link', { name: 'devices' });
    this.groupsLink = page.getByRole('link', { name: 'groups' });
    this.joinFormLink = page.getByRole('link', { name: 'join form' });
    this.listActionFormLink = page.getByRole('link', { name: 'list action form' });
    this.skipToMainContent = page.getByText('skip to main content home');
  }

  async goto() {
    await this.page.goto('/');
  }

  async verifyAllLinksVisible() {
    await expect(this.homeLink).toBeVisible();
    await expect(this.devicesLink).toBeVisible();
    await expect(this.groupsLink).toBeVisible();
    await expect(this.joinFormLink).toBeVisible();
    await expect(this.listActionFormLink).toBeVisible();
  }

  async clickSkipToMainContent() {
    await this.skipToMainContent.click();
  }
}
