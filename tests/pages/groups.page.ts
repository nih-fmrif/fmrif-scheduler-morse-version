import { Page, Locator, expect } from '@playwright/test';
import { waitForAppShell } from '../utils/test-helpers';

export class GroupsPage {
  readonly page: Page;
  readonly groupsLink: Locator;
  readonly activeGroupsLink: Locator;
  readonly inactiveGroupsLink: Locator;
  readonly addGroupLink: Locator;
  readonly homeLink: Locator;
  readonly testGroupLink: Locator;
  readonly adminGroupLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.groupsLink = page.getByRole('link', { name: 'groups', exact: true });
    this.activeGroupsLink = page.getByRole('link', { name: 'active groups', exact: true });
    this.inactiveGroupsLink = page.getByRole('link', { name: 'inactive groups' });
    this.addGroupLink = page.getByRole('link', { name: 'add group' });
    this.homeLink = page.getByRole('link', { name: 'home' });
    this.testGroupLink = page.getByRole('link', { name: 'Test' });
    this.adminGroupLink = page.getByRole('link', { name: 'admin' });
  }

  async goto() {
    await this.page.goto('/groups');
    await waitForAppShell(this.page);
  }

  async verifyPageElements() {
    await waitForAppShell(this.page);
    await expect(this.groupsLink).toBeVisible();
    await expect(this.activeGroupsLink).toBeVisible();
    await expect(this.inactiveGroupsLink).toBeVisible();
    await expect(this.addGroupLink).toBeVisible();
    await expect(this.page.locator('article.list-with-description')).toBeVisible();
  }
}
