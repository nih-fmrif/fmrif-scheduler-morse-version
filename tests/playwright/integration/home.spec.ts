import { test, expect } from '../support/auth-fixture';
import { HomePage } from '../pages/home.page';

test.describe('Home Page', () => {
  let homePage: HomePage;

  test.beforeEach(async ({ page }) => {
    homePage = new HomePage(page);
  });

  test('should display all navigation links', async () => {
    await homePage.verifyAllLinksVisible();
  });

  test('should allow skipping to main content', async () => {
    await homePage.clickSkipToMainContent();
  });

  test('should log out and redirect to login page', async ({ page }) => {
    await page.getByRole('button', { name: 'Logout' }).click();
    await expect(page).toHaveURL(/\/auth\/login(?:\?.*)?$/);
    await expect(page.getByRole('button', { name: /Login with NIH Credentials/i })).toBeVisible();
  });
});
