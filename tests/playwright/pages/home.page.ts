import { Page, Locator, expect } from '@playwright/test';
import { waitForAppShell } from '../utils/test-helpers';

export class HomePage {
  readonly page: Page;
  readonly heading: Locator;
  readonly devicesSection: Locator;
  readonly groupsSection: Locator;
  readonly firstDeviceCard: Locator;
  readonly joinFormLink: Locator;
  readonly emailLink: Locator;
  readonly userMenuToggle: Locator;
  readonly skipToMainContent: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole('heading', { name: /FMRIF Scheduler/i });
    this.devicesSection = page.locator('[data-home-section="devices"]');
    this.groupsSection = page.locator('[data-home-section="groups"]');
    this.firstDeviceCard = this.devicesSection.locator('a.list-card').first();
    this.joinFormLink = page.getByRole('link', { name: 'join form' });
    this.emailLink = page.locator('.user-menu-panel').getByRole('link', { name: 'email' });
    this.userMenuToggle = page.locator('#user-menu-toggle');
    this.skipToMainContent = page.getByRole('link', { name: 'skip to main content' });
  }

  async goto() {
    await this.page.goto('/', { waitUntil: 'domcontentloaded' });
    await waitForAppShell(this.page);
  }

  async verifyAllLinksVisible() {
    await waitForAppShell(this.page);
    await expect(this.heading).toBeVisible();
    await expect(this.devicesSection).toBeVisible();
    await expect(this.groupsSection).toBeVisible();
    await expect(this.firstDeviceCard).toBeVisible();
    await expect(this.userMenuToggle).toBeVisible();
    await this.openUserMenu();
    await expect(this.emailLink).toBeVisible();
  }

  async clickSkipToMainContent() {
    await this.skipToMainContent.click();
  }

  async openUserMenu() {
    await this.userMenuToggle.click();
    await expect(this.page.locator('.user-menu[open]')).toBeVisible();
  }
}
