import { test, expect } from '@playwright/test';
import { GroupsPage } from './pages/groups.page';
import { GroupDetailsPage } from './pages/group-details.page';
import { GroupEditPage } from './pages/group-edit.page';

test.describe('Groups Section', () => {
  let groupsPage: GroupsPage;
  let groupDetailsPage: GroupDetailsPage;
  let groupEditPage: GroupEditPage;

  test.beforeEach(async ({ page }) => {
    groupsPage = new GroupsPage(page);
    groupDetailsPage = new GroupDetailsPage(page);
    groupEditPage = new GroupEditPage(page);
  });

  test('should navigate through groups list', async () => {
    await groupsPage.goto();
    await groupsPage.verifyPageElements();
    await groupsPage.activeGroupsLink.click();
    await groupsPage.inactiveGroupsLink.click();
    await groupsPage.addGroupLink.click();
  });

  test('should view and edit test group', async ({ page }) => {
    await groupsPage.goto();
    await groupsPage.testGroupLink.click();
    await groupDetailsPage.verifyPageElements();
    
    // Test navigation through group options
    await groupDetailsPage.viewGroupLink.click();
    await groupDetailsPage.membershipLink.click();
    await groupDetailsPage.changePILink.click();
    await groupDetailsPage.editLink.click();
    
    // Test edit functionality
    await groupEditPage.verifyEditForm();
    await groupEditPage.saveButton.click();
    await expect(page.getByText('Test has been updated')).toBeVisible();
  });

  test('should add new group', async () => {
    await groupsPage.goto();
    await groupsPage.addGroupLink.click();
    await groupEditPage.verifyAddForm();
    await groupEditPage.createButton.click();
  });

  test('should view admin group', async () => {
    await groupsPage.goto();
    await groupsPage.adminGroupLink.click();
    await groupsPage.groupsLink.click();
  });
});
