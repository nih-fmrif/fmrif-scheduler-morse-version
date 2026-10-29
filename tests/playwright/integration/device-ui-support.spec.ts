import { expect, test } from '../support/auth-fixture';
import {
  grantDeviceSupportPermission,
  isMockMode,
  openFutureDeviceGrid,
  openSlotInspectorEditor,
} from '../utils/device-ui-interactions';

test.describe('Schedule UI interactions', () => {
  test.skip(!isMockMode, 'Schedule editor interactions require mock fixtures.');
  test.setTimeout(90000);

  test('should enable medical support handlers when device medical permission exists', async ({ page }) => {
    await grantDeviceSupportPermission(page, 'd', 'medical');
    await openFutureDeviceGrid(page, 'd', '2035-03-18');

    const { slotEditor } = await openSlotInspectorEditor(page, 8, 0, {
      group: 'BEI',
      member: 'user0048',
    });

    await slotEditor.locator('input[id^="med-requested-"]').first().check();
    const medHandler = slotEditor.locator('input[id^="med-handler-"]').first();

    await expect(medHandler).toBeEnabled();
    await expect.poll(async () => await medHandler.getAttribute('list')).toBe('med');
    await medHandler.fill('user0049');
    await expect(medHandler).toHaveValue('user0049');
  });

  test('should clear saved medical handlers when medical coverage is unchecked', async ({ page }) => {
    await grantDeviceSupportPermission(page, 'd', 'medical');
    await openFutureDeviceGrid(page, 'd', '2035-03-20');

    const initialEditor = await openSlotInspectorEditor(page, 8, 0, {
      group: 'BEI',
      member: 'user0048',
    });
    const initialRequested = initialEditor.slotEditor.locator('input[id^="med-requested-"]').first();
    const initialHandler = initialEditor.slotEditor.locator('input[id^="med-handler-"]').first();

    await initialRequested.check();
    await initialHandler.fill('user0049');
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await page.locator('#inspector-save').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();

    const clearedEditor = await openSlotInspectorEditor(page, 8, 0, {
      group: 'BEI',
      member: 'user0048',
    });
    const clearedRequested = clearedEditor.slotEditor.locator('input[id^="med-requested-"]').first();
    const clearedHandler = clearedEditor.slotEditor.locator('input[id^="med-handler-"]').first();

    await expect(clearedRequested).toBeChecked();
    await expect(clearedHandler).toHaveValue('user0049');
    await clearedRequested.uncheck();
    await expect(clearedHandler).toBeDisabled();
    await expect(clearedHandler).toHaveValue('');

    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await page.locator('#inspector-save').click();
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();

    await page.reload();

    const reopenedEditor = await openSlotInspectorEditor(page, 8, 0, {
      group: 'BEI',
      member: 'user0048',
    });
    const reopenedRequested = reopenedEditor.slotEditor.locator('input[id^="med-requested-"]').first();
    const reopenedHandler = reopenedEditor.slotEditor.locator('input[id^="med-handler-"]').first();

    await expect(reopenedRequested).not.toBeChecked();
    await expect(reopenedHandler).toBeDisabled();
    await expect(reopenedHandler).toHaveValue('');
    await expect(page.locator('#inspector-dialog-container .editor-inspector-detail-summary')).toContainText(
      'no support requests'
    );
  });

  test('should allow retrying medical handler conflicts from the same draft', async ({ page }) => {
    await grantDeviceSupportPermission(page, 'd', 'medical');
    await openFutureDeviceGrid(page, 'd', '2035-03-19');

    const baseline = await openSlotInspectorEditor(page, 8, 0, {
      group: 'BEI',
      member: 'user0048',
    });
    await baseline.slotEditor.locator('input[id^="med-requested-"]').first().check();
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await page.locator('#inspector-save').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();

    const conflictEditor = await openSlotInspectorEditor(page, 8, 0, {
      group: 'BEI',
      member: 'user0048',
    });
    const medHandler = conflictEditor.slotEditor.locator('input[id^="med-handler-"]').first();
    await expect(medHandler).toBeEnabled();

    let postCount = 0;
    const postPayloads: Array<Array<{ med?: { handler?: [string, string] } }>> = [];
    await page.route('**/device/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      postCount += 1;
      const raw = request.postData() ?? '{}';
      const parsed = JSON.parse(raw);
      const payload = parsed?.payload ?? {};
      const diffs = Array.isArray(payload.diffs)
        ? (payload.diffs as Array<{ id?: string; med?: { handler?: [string, string] } }>)
        : [];
      postPayloads.push(diffs);

      if (postCount === 1) {
        const diff = diffs[0];
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            errors:
              typeof diff?.id === 'string'
                ? {
                    [diff.id]: [
                      {
                        type: 'overwrote',
                        key: 'medical handler',
                        expected: 'user0019',
                        got: '',
                      },
                    ],
                  }
                : {},
          }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          saved: diffs.length,
          notifications: [],
        }),
      });
    });

    await medHandler.fill('user0049');
    await page.locator('#inspector-save').click();

    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/overwritten by another user/i);
    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();

    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await expect(page.locator('#review-pending')).not.toContainText('error');

    await page.locator('#inspector-save').click();
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);

    expect(postCount).toBe(2);
    expect(postPayloads[0]?.[0]?.med?.handler).toEqual(['', 'user0049']);
    expect(postPayloads[1]?.[0]?.med?.handler).toEqual(['user0019', 'user0049']);
  });
});
