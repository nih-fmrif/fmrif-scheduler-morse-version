import { Page } from '@playwright/test';

export async function loginAsSuperuser(page: Page) {
  // Add login helper if needed
}

export async function navigateToSection(page: Page, section: string) {
  await page.goto('/');
  await page.getByRole('link', { name: section }).click();
}
