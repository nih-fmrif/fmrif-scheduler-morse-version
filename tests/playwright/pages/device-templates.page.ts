import { Page, Locator, expect } from '@playwright/test';
import { waitForAppShell } from '../utils/test-helpers';

export class DeviceTemplatesPage {
  readonly page: Page;
  readonly applyLink: Locator;
  readonly activeLink: Locator;
  readonly inactiveLink: Locator;
  readonly addTemplateLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.applyLink = page.getByRole('link', { name: 'apply' });
    this.activeLink = page.getByRole('link', { name: 'active', exact: true });
    this.inactiveLink = page.getByRole('link', { name: 'inactive' });
    this.addTemplateLink = page.getByRole('link', { name: 'add template' });
  }

  async verifyPageElements() {
    await waitForAppShell(this.page);
    await expect(this.applyLink).toBeVisible();
    await expect(this.activeLink).toBeVisible();
    await expect(this.inactiveLink).toBeVisible();
    await expect(this.addTemplateLink).toBeVisible();
    const pageBody = this.page.locator('div.body.device_tmpl');
    await expect(pageBody).toBeVisible();
    await expect(pageBody.locator('form.template-apply, p.note').first()).toBeVisible();
  }
}
