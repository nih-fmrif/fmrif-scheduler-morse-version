import type { Page } from '@playwright/test';

function normalizeUsername(username: string): string {
  const trimmed = username.trim();
  if (!trimmed || trimmed.includes('@')) {
    return trimmed;
  }
  return `${trimmed}@nih.gov`;
}

export async function signInWithCredentials(page: Page, username: string, password: string) {
  await page.getByRole('button', { name: /Login with NIH Credentials/i }).click();

  const useAnotherAccount = page.getByText(/Use another account/i);
  if (await useAnotherAccount.isVisible({ timeout: 2000 }).catch(() => false)) {
    await useAnotherAccount.click();
  }

  const emailInput = page.locator('input[type="email"], input[name="loginfmt"], #i0116');
  await emailInput.first().waitFor({ state: 'visible', timeout: 20000 });
  await emailInput.first().fill(normalizeUsername(username));

  const continueButton = page.locator('#idSIButton9');
  await continueButton.waitFor({ state: 'visible', timeout: 20000 });
  await continueButton.click();

  const passwordInput = page.locator('input[type="password"], input[name="passwd"], #i0118');
  await passwordInput.first().waitFor({ state: 'visible', timeout: 20000 });
  await passwordInput.first().fill(password);
  await continueButton.waitFor({ state: 'visible', timeout: 20000 });
  await continueButton.click();

  const noButton = page.locator('#idBtn_Back');
  const hasNoButton = await noButton.waitFor({ state: 'visible', timeout: 15000 }).then(
    () => true,
    () => false
  );
  if (hasNoButton) {
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => null),
      noButton.click(),
    ]);
    return;
  }

  const yesButton = page.locator('#idSIButton9');
  const hasYesButton = await yesButton.waitFor({ state: 'visible', timeout: 2000 }).then(
    () => true,
    () => false
  );
  if (hasYesButton) {
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => null),
      yesButton.click(),
    ]);
  }
}
