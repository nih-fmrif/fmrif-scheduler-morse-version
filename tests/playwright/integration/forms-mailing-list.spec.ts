import { test, expect } from '../support/auth-fixture';
import { ListActionFormPage } from '../pages/list-action-form.page';
import {
  clearMailpitMessages,
  getMailpitMessage,
  mailpitAvailable,
  resolveMailpitApiBaseURL,
  waitForMailpitMessage,
} from '../utils/mailpit-api';
import { waitForAppShell } from '../utils/test-helpers';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';
const mailpitApiBaseURL = resolveMailpitApiBaseURL();
const mailSuppressed = (process.env.MAIL__SUPPRESS_SEND ?? 'false').trim().toLowerCase() !== 'false';

test.describe('Forms Mailing Lists', () => {
  test('should show validation when no lists are selected', async ({ page }) => {
    const listActionFormPage = new ListActionFormPage(page);

    await listActionFormPage.goto();
    await listActionFormPage.verifyPageElements();
    await page.getByLabel('email').fill('synthetic-mailing-list-test@nih.gov');
    await listActionFormPage.submitForm();
    await expect(page).toHaveURL(/\/mailing-lists$/);
    await expect(page.getByText(/At least one list must be selected/i)).toBeVisible();
  });

  test('should submit mailing list updates and redirect home', async ({ page }) => {
    test.skip(!isMockMode, 'Redirect + flash assertion is mock-only and data/role dependent.');

    const listActionFormPage = new ListActionFormPage(page);

    await listActionFormPage.goto();
    await listActionFormPage.verifyPageElements();

    await page.getByLabel('email').fill('synthetic-mailing-list-test@nih.gov');
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

  test('should deliver mailing list notifications to mailpit', async ({ page, request }) => {
    test.skip(!isMockMode, 'Mailpit flow uses mock auth profile switching.');
    test.skip(!mailpitApiBaseURL, 'Set MAILPIT__PORT or PLAYWRIGHT_MAILPIT_API_BASE_URL.');
    test.skip(mailSuppressed, 'Set MAIL__SUPPRESS_SEND=false for delivery verification.');

    const apiBaseURL = mailpitApiBaseURL as string;
    if (!(await mailpitAvailable(request, apiBaseURL))) {
      test.skip(true, `Mailpit API is not reachable at ${apiBaseURL}.`);
      return;
    }

    await clearMailpitMessages(request, apiBaseURL);
    try {
      const listActionFormPage = new ListActionFormPage(page);

      await listActionFormPage.goto();
      await listActionFormPage.verifyPageElements();

      await page.getByLabel('email').fill('synthetic-mailing-list-test@nih.gov');
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

      const summary = await waitForMailpitMessage(
        request,
        apiBaseURL,
        (message) => message.Subject === 'Automated list change',
        { timeoutMs: 12000, pollMs: 250 }
      );
      expect(summary).not.toBeNull();
      if (!summary) {
        throw new Error('Mailpit message lookup timed out.');
      }

      const detail = await getMailpitMessage(request, apiBaseURL, summary.ID);
      expect(detail.From?.Address?.toLowerCase()).toBe('synthetic-mailing-list-test@nih.gov');
      expect(String(detail.Text ?? '').toLowerCase()).toContain('subscribe');

      const recipients = detail.To ?? [];
      expect(recipients.length).toBeGreaterThan(0);
      expect(Boolean(recipients[0]?.Address)).toBeTruthy();
    } finally {
      await clearMailpitMessages(request, apiBaseURL);
    }
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
