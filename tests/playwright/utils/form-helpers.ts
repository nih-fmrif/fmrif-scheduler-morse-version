import { Page } from '@playwright/test';

export async function fillFormField(page: Page, fieldName: string, value: string) {
  await page.getByLabel(fieldName).fill(value);
}

export async function submitForm(page: Page) {
  await page.getByRole('button', { name: 'submit' }).click();
}

export async function verifyFormValidation(page: Page, errorMessage: string) {
  await page.getByText(errorMessage).isVisible();
}
