import { test } from '@playwright/test';
import { JoinFormPage } from './pages/join-form.page';
import { ListActionFormPage } from './pages/list-action-form.page';

test.describe('Forms Section', () => {
  let joinFormPage: JoinFormPage;
  let listActionFormPage: ListActionFormPage;

  test.beforeEach(async ({ page }) => {
    joinFormPage = new JoinFormPage(page);
    listActionFormPage = new ListActionFormPage(page);
  });

  // test.describe('Join Form', () => {
  //   test('should navigate to join form page', async () => {
  //     await joinFormPage.goto();
  //     await joinFormPage.verifyPageElements();
  //   });

  //   test('should return to home from join form', async () => {
  //     await joinFormPage.goto();
  //     await joinFormPage.homeLink.click();
  //   });
  // });

  test.describe('List Action Form', () => {
    test('should navigate to list action form page', async () => {
      await listActionFormPage.goto();
      await listActionFormPage.verifyPageElements();
    });

    test('should submit list action form', async () => {
      await listActionFormPage.goto();
      await listActionFormPage.submitForm();
    });
  });
});
