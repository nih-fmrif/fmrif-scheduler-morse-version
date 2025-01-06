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
    this.logoutLink = page.getByRole('link', { name: 'Logout' });
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

  async logout() {
    await this.logoutLink.click();
  }

  async verifyErrorMessage() {
    await expect(this.errorMessage).toBeVisible();
  }

  async verifySuccessfulLogin() {
    await expect(this.page.getByText('Successfully logged in')).toBeVisible();
    await expect(this.logoutLink).toBeVisible();
  }

  async verifyLoggedOut() {
    await expect(this.page.getByText('Successfully logged out')).toBeVisible();
    await expect(this.logoutLink).not.toBeVisible();
  }
}