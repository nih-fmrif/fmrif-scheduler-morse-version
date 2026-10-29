import { test, expect } from '../support/auth-fixture';

test.describe('Technologist Join Access', () => {
  test.describe('member profile', () => {
    test.use({ authProfile: 'member' });

    test('should deny /join/tech for users outside DEV', async ({ page }) => {
      await page.goto('/join/tech');
      await expect(page.getByRole('heading', { name: /access denied/i })).toBeVisible();
      await expect(
        page.getByText(/The application administrators have been notified/i)
      ).toBeVisible();
    });
  });

  test.describe('dev profile', () => {
    test.use({ authProfile: 'dev' });

    test('should allow /join/tech for DEV users who are not technologists', async ({
      page,
    }) => {
      await page.goto('/join/tech');
      await expect(page).toHaveURL(/\/join\/tech$/);
      await expect(
        page.getByText(/Technical scan volunteers may not be scanned more than 3 hours per week/i)
      ).toBeVisible();
      await expect(page.getByRole('button', { name: 'submit' })).toBeVisible();
    });
  });

  test.describe('tech profile', () => {
    test.use({ authProfile: 'tech' });

    test('should deny /join/tech for users already on technologist list', async ({ page }) => {
      await page.goto('/join/tech');
      await expect(page.getByRole('heading', { name: /access denied/i })).toBeVisible();
      await expect(
        page.getByText(/The application administrators have been notified/i)
      ).toBeVisible();
    });
  });
});
