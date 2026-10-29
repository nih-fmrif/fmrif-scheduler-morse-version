import { test, expect } from '../support/auth-fixture';
import { ListActionFormPage } from '../pages/list-action-form.page';
import { waitForAppShell } from '../utils/test-helpers';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('Forms Section', () => {
  test('should show validation when no lists are selected', async ({ page }) => {
    const listActionFormPage = new ListActionFormPage(page);

    await listActionFormPage.goto();
    await listActionFormPage.verifyPageElements();
    await page.getByLabel('email').fill('contact001@example.org');
    await listActionFormPage.submitForm();
    await expect(page).toHaveURL(/\/mailing-lists$/);
    await expect(page.getByText(/At least one list must be selected/i)).toBeVisible();
  });

  test('should submit mailing list updates and redirect home', async ({ page }) => {
    test.skip(!isMockMode, 'Redirect + flash assertion is mock-only and data/role dependent.');

    const listActionFormPage = new ListActionFormPage(page);

    await listActionFormPage.goto();
    await listActionFormPage.verifyPageElements();

    await page.getByLabel('email').fill('contact001@example.org');
    await page.getByLabel('name').fill('Test Admin');

    const firstListOption = page
      .locator('form.mailing-list-form fieldset[data-name="lists"] input[type="checkbox"]')
      .first();
    await expect(firstListOption).toBeVisible();
    await firstListOption.check();

    await listActionFormPage.submitForm();
    await expect(page).toHaveURL(/\/$/);
    await expect(
      page.getByText(/your mailing list subscription status has been updated/i)
    ).toBeVisible();
  });

  test('should show join form error for invalid department selection', async ({ page }) => {
    test.skip(!isMockMode, 'Join form validation path depends on mock test profile access.');

    await page.goto('/join');
    await waitForAppShell(page);

    const departmentInput = page.getByLabel('department');
    await expect(page.locator('form.join-form')).toBeVisible();
    await departmentInput.fill('INVALID-DEPARTMENT-FOR-TEST');
    await page.getByRole('button', { name: 'submit' }).click();

    await expect(page).toHaveURL(/\/join$/);
    const isValid = await departmentInput.evaluate(
      (elm) => (elm as HTMLInputElement).validity.valid
    );
    const validationMessage = await departmentInput.evaluate(
      (elm) => (elm as HTMLInputElement).validationMessage
    );
    expect(isValid).toBe(false);
    expect(validationMessage.toLowerCase()).toContain('invalid department');
  });
});

test.describe('Technologist Join Access', () => {
  test.describe('member profile', () => {
    test.use({ authProfile: 'member' });

    test('should deny /join/tech for users outside DEV', async ({ page }) => {
      await page.goto('/join/tech');
      await expect(
        page.getByText(
          /Only DEV members who have not become technologists already may access this form/i
        )
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
      await expect(
        page.getByText(
          /Only DEV members who have not become technologists already may access this form/i
        )
      ).toBeVisible();
    });
  });
});
