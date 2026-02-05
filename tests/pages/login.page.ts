// tests/pages/login.page.ts
import { Page, Locator, expect } from '@playwright/test';

export class LoginPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly subtitle: Locator;
  readonly loginButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole('heading', { name: /Device Scheduler/i });
    this.subtitle = page.getByText(/Sign in with your NIH credentials/i);
    this.loginButton = page.getByRole('button', { name: /Login with NIH Credentials/i });
  }

  async goto() {
    await this.page.goto('/auth/login');
  }

  async verifyPageElements() {
    await expect(this.heading).toBeVisible();
    await expect(this.subtitle).toBeVisible();
    await expect(this.loginButton).toBeVisible();
  }

  async startLogin() {
    await this.loginButton.click();
  }

  async verifyLoggedIn() {
    await expect(this.page.getByText(/logged in as/i)).toBeVisible();
  }
}
