import { test, expect } from '../support/auth-fixture';
import { GroupsPage } from '../pages/groups.page';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('Groups Section', () => {
  test.skip(!isMockMode, 'Groups list fixture assertions only run in PLAYWRIGHT_AUTH_MODE=mock.');

  test('should render groups list views', async ({ page }) => {
    const groupsPage = new GroupsPage(page);

    await groupsPage.goto();
    await groupsPage.verifyPageElements();

    await groupsPage.activeGroupsLink.click();
    await expect(page).toHaveURL(/\/groups$/);
    await expect(page.locator('article.list-with-description')).toBeVisible();

    await groupsPage.inactiveGroupsLink.click();
    await expect(page).toHaveURL(/\/groups\/inactive$/);
    await expect(page.locator('article.list-with-description')).toBeVisible();
  });
});
