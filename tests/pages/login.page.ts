// tests/pages/login.page.ts
import { Page, Locator, expect } from '@playwright/test';

export class LoginPage {
  readonly page: Page;
  readonly usernameInput: Locator;
  readonly passwordInput: Locator;
  readonly submitButton: Locator;
  readonly logoutLink: Locator;
  readonly errorMessage: Locator;

  constructor(page: Page) {
    this.page = page;
    this.usernameInput = page.getByLabel('Username');
    this.passwordInput = page.getByLabel('Password'); 
    this.submitButton = page.getByRole('button', { name: 'Login' });
    this.logoutLink = page.getByRole('link', { name: 'logout' });
    this.errorMessage = page.getByText('Invalid username or password');
  }

  async goto() {
    await this.page.goto('/auth/login');
  }

  async verifyPageElements() {
    await expect(this.usernameInput).toBeVisible();
    await expect(this.passwordInput).toBeVisible();
    await expect(this.submitButton).toBeVisible();
  }

  async login(username: string, password: string) {
    await this.usernameInput.fill(username);
    await this.passwordInput.fill(password);
    await this.submitButton.click();
  }

  async verifySuccessfulLogin() {
    if (process.env.RBAC__SUPERUSER_MODE === 'false') {
      await this.page.waitForURL('/**');
      await expect(this.page.getByText(/logged in as/)).toBeVisible();
    } else {
      await this.page.goto('/');
      await expect(this.page.getByText('logged in as superuser')).toBeVisible();
    }
  }

  async verifyErrorMessage() {
    await expect(this.errorMessage).toBeVisible();
  }

  async logout() {
    await this.logoutLink.click();
  }

  async verifyLoggedOut() {
    await expect(this.logoutLink).not.toBeVisible();
  }
}
