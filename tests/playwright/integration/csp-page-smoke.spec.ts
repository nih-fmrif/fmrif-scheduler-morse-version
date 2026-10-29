import { expect, test as base } from '@playwright/test';

import { test as authTest } from '../support/auth-fixture';

type RuntimeErrors = {
  consoleErrors: string[];
  pageErrors: string[];
};

function trackRuntimeErrors(page: import('@playwright/test').Page): RuntimeErrors {
  const runtimeErrors: RuntimeErrors = {
    consoleErrors: [],
    pageErrors: [],
  };

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      runtimeErrors.consoleErrors.push(msg.text());
    }
  });
  page.on('pageerror', (err) => {
    runtimeErrors.pageErrors.push(err.message);
  });

  return runtimeErrors;
}

function expectBaselineCsp(response: import('@playwright/test').Response | null) {
  expect(response).not.toBeNull();
  expect(response?.ok()).toBeTruthy();
  const headers = response?.headers() ?? {};
  const csp =
    headers['content-security-policy'] ?? headers['content-security-policy-report-only'] ?? '';
  expect(csp).toContain("default-src 'self'");
  expect(csp).toContain("script-src 'self'");
  expect(csp).toContain("'strict-dynamic'");
  expect(csp).toMatch(/script-src[^;]*'nonce-[^']+'/);
  expect(csp).toContain("script-src-attr 'none'");
  expect(csp).toContain("style-src 'self'");
  expect(csp).toContain("style-src-attr 'none'");
  expect(csp).toContain('report-to csp-endpoint');
  expect(headers['reporting-endpoints']).toBe('csp-endpoint="/csp-report"');
}

base.describe('Public CSP Page Smokes', () => {
  base('auth callback page loads without CSP/runtime errors', async ({ page }) => {
    const runtimeErrors = trackRuntimeErrors(page);
    const response = await page.goto('/auth/callback?next=%2F');

    expectBaselineCsp(response);
    await expect(page).toHaveURL(/\/auth\/login(?:\?|$)/);
    await expect(
      page.getByRole('button', { name: /login with nih credentials/i })
    ).toBeVisible();
    expect(runtimeErrors.consoleErrors).toEqual([]);
    expect(runtimeErrors.pageErrors).toEqual([]);
  });
});

authTest.describe('Authenticated CSP Page Smokes', () => {
  authTest.use({ authProfile: 'admin' });

  authTest('RBAC page loads without CSP/runtime errors', async ({ page }) => {
    const runtimeErrors = trackRuntimeErrors(page);
    const response = await page.goto('/rbac?scope=device');

    expectBaselineCsp(response);
    await expect(page.getByRole('heading', { name: /rbac explorer/i })).toBeVisible();
    expect(runtimeErrors.consoleErrors).toEqual([]);
    expect(runtimeErrors.pageErrors).toEqual([]);
  });

  authTest('template editor loads without CSP/runtime errors', async ({ page }) => {
    const runtimeErrors = trackRuntimeErrors(page);
    const response = await page.goto('/device/d/templates/edit/i');

    expectBaselineCsp(response);
    await expect(page.locator('.editor-inspector')).toBeVisible();
    expect(runtimeErrors.consoleErrors).toEqual([]);
    expect(runtimeErrors.pageErrors).toEqual([]);
  });
});
