import { test, expect } from '@playwright/test';
import { LoginPage } from './pages/login.page';

test.describe('Authentication', () => {
  let loginPage: LoginPage;

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page);
    await loginPage.goto();
  });

  test('should show login form', async () => {
    await loginPage.verifyPageElements();
  });

  test('should show error on invalid credentials', async () => {
    await loginPage.login('invalid', 'invalid');
    await loginPage.verifyErrorMessage();
  });

  test('should login successfully with valid credentials', async () => {
    await loginPage.login('euler', 'password');
    await loginPage.verifySuccessfulLogin();
  });

  test('should logout successfully', async () => {
    await loginPage.login('euler', 'password');
    await loginPage.logout();
    await loginPage.verifyLoggedOut();
  });
});