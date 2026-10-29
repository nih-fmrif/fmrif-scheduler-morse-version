import { expect, test as base } from '@playwright/test';

import { ensureAuthenticated } from './auth-session';

type AuthFixtures = {
  authProfile: string;
};

export const test = base.extend<AuthFixtures>({
  authProfile: ['admin', { option: true }],
  page: async ({ page, authProfile }, use, testInfo) => {
    await ensureAuthenticated(page, testInfo, authProfile);
    await use(page);
  },
});

export { expect };
