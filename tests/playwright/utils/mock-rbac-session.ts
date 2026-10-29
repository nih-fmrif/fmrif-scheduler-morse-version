import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

export type MockRbacProfile = 'admin' | 'member' | 'inactive';

const sharedSecret = process.env.AUTH_TEST__SHARED_SECRET;

export async function ensureProfileSession(
  page: Page,
  profile: MockRbacProfile,
  username: string
): Promise<void> {
  if (!sharedSecret) {
    throw new Error('AUTH_TEST__SHARED_SECRET must be set for mock RBAC coverage tests.');
  }

  const response = await page.request.post('/auth/test/session', {
    headers: {
      'X-Test-Auth-Secret': sharedSecret,
      'Content-Type': 'application/json',
    },
    data: { profile },
  });

  expect(response.ok()).toBeTruthy();
  await page.goto('/');
  await expect(page.locator('#user-menu-toggle')).toContainText(new RegExp(username, 'i'));
}
