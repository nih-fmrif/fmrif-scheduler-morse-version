import type { Page } from '@playwright/test';

export async function signInWithCredentials(page: Page, username: string, password: string) {
  await page.getByRole('button', { name: /Login with NIH Credentials/i }).click();

  const useAnotherAccount = page.getByText(/Use another account/i);
  if (await useAnotherAccount.isVisible({ timeout: 2000 }).catch(() => false)) {
    await useAnotherAccount.click();
  }

  const emailInput = page.locator('input[type="email"], input[name="loginfmt"], #i0116');
  await emailInput.first().waitFor({ state: 'visible', timeout: 20000 });
  await emailInput.first().fill(username);

  const nextButton = page.locator('#idSIButton9, input[type="submit"], button[type="submit"]');
  await nextButton.first().click();

  const passwordInput = page.locator('input[type="password"], input[name="passwd"], #i0118');
  await passwordInput.first().waitFor({ state: 'visible', timeout: 20000 });
  await passwordInput.first().fill(password);
  await nextButton.first().click();

  const staySignedIn = page.locator('#idSIButton9');
  if (await staySignedIn.isVisible({ timeout: 5000 }).catch(() => false)) {
    await staySignedIn.click();
  }
}
