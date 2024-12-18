import { test, expect } from '@playwright/test';
import { HomePage } from './pages/home.page';

test.describe('Home Page', () => {
  let homePage: HomePage;

  test.beforeEach(async ({ page }) => {
    homePage = new HomePage(page);
    await homePage.goto();
  });

  test('should display all navigation links', async () => {
    await homePage.verifyAllLinksVisible();
  });

  test('should allow skipping to main content', async () => {
    await homePage.clickSkipToMainContent();
  });
});
