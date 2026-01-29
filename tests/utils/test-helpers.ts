import { Page, expect } from '@playwright/test';

export async function loginAsSuperuser(page: Page) {
  // Add login helper if needed
}

export async function waitForAppShell(page: Page) {
  await expect(page.locator('nav.breadcrumb')).toBeVisible();
  await expect(page.locator('section.login-info')).toBeVisible();
}

export async function navigateToSection(page: Page, section: string) {
  await page.goto('/');
  await waitForAppShell(page);
  await page.getByRole('link', { name: section }).click();
}
