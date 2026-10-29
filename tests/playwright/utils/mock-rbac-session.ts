import type { Page, TestInfo } from '@playwright/test';
import { expect } from '@playwright/test';
import { mockSessionKeyFor } from './mock-session-key';

export type MockRbacProfile = 'admin' | 'member' | 'inactive';

type MockSessionOptions = {
  groupPiGroups?: string[];
  resetProfileState?: boolean;
  testInfo: TestInfo;
};

const sharedSecret = process.env.AUTH_TEST__SHARED_SECRET;

export async function ensureProfileSession(
  page: Page,
  profile: MockRbacProfile,
  username: string,
  options: MockSessionOptions
): Promise<void> {
  if (!sharedSecret) {
    throw new Error('AUTH_TEST__SHARED_SECRET must be set for mock RBAC coverage tests.');
  }
  const sessionKey = mockSessionKeyFor(options.testInfo);
  const effectiveGroupPiGroups =
    options.groupPiGroups?.length === 1 && options.groupPiGroups[0] === 'GPI'
      ? [`GPI${sessionKey}`.slice(0, 10).toUpperCase()]
      : options.groupPiGroups;

  const response = await page.request.post('/auth/test/session', {
    headers: {
      'X-Test-Auth-Secret': sharedSecret,
      'Content-Type': 'application/json',
    },
    data: {
      profile,
      reset_profile_state: options.resetProfileState ?? true,
      session_key: sessionKey,
      ...(effectiveGroupPiGroups && effectiveGroupPiGroups.length > 0
        ? { group_pi_groups: effectiveGroupPiGroups }
        : {}),
    },
  });

  expect(response.ok()).toBeTruthy();
  await page.goto('/');
  await expect(page.locator('#user-menu-toggle')).toContainText(new RegExp(username, 'i'));
}

export async function ensureGroupPiSession(
  page: Page,
  username: string = 'test-member',
  groupId: string = 'GPI',
  options: MockSessionOptions
): Promise<void> {
  await ensureProfileSession(page, 'member', username, {
    ...options,
    groupPiGroups: [groupId],
  });
}

export async function ensureDevPiSession(
  page: Page,
  username: string = 'test-member',
  options: MockSessionOptions
): Promise<void> {
  await ensureGroupPiSession(page, username, 'DEV', options);
}
