import { expect, test } from '../support/auth-fixture';
import {
  editSlotThroughInspector,
  isMockMode,
  jumpDay,
  openFutureBlankDeviceGrid,
  openFutureBlankSchedulableDeviceGrid,
  openSlotInspectorEditor,
  pickSchedulableAssignment,
  scopedFutureStart,
} from '../utils/device-ui-interactions';

test.describe('Schedule UI interactions', () => {
  test.skip(!isMockMode, 'Schedule editor interactions require mock fixtures.');
  test.setTimeout(90000);

  test('should keep pending drafts after exiting the inspector', async ({ page }) => {
    await openFutureBlankDeviceGrid(page);
    const assignment = await pickSchedulableAssignment(page);
    test.skip(!assignment, 'No schedulable group/member assignment is available in this fixture.');

    await editSlotThroughInspector(page, 8, 0, assignment);
    await expect(page.locator('#review-pending')).toContainText('Review pending');

    const row = page.locator('#row-8');
    await row.locator('td').nth(0).dblclick();
    const dialog = page.locator('#inspector-dialog-container .dialog-box-container');
    await expect(dialog).toBeVisible();
    const slotEditor = page.locator('#inspector-slot-editor');
    await expect(slotEditor.locator('input[id^="grp-"]').first()).toHaveValue(assignment.group);
    await expect(slotEditor.locator('input[id^="mem-"]').first()).toHaveValue(assignment.member);
  });

  test('should save the selected slot directly without opening review', async ({ page }) => {
    await openFutureBlankDeviceGrid(page, '2035-02-02');
    const assignment = await pickSchedulableAssignment(page);
    test.skip(!assignment, 'No schedulable group/member assignment is available in this fixture.');

    const postPayloads: Array<{ diffs: unknown[]; notify: boolean }> = [];
    await page.route('**/device/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      const raw = request.postData() ?? '{}';
      const parsed = JSON.parse(raw);
      const payload = parsed?.payload ?? {};
      const diffs = Array.isArray(payload.diffs)
        ? (payload.diffs as Array<{ id?: string }>)
        : [];
      postPayloads.push({ diffs, notify: Boolean(payload.notify) });
      const idMap = Object.fromEntries(
        diffs
          .filter((diff) => typeof diff.id === 'string' && diff.id.startsWith('new-'))
          .map((diff, index) => [diff.id, 9200 + index])
      );
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          saved: diffs.length,
          notifications: [],
          id_map: idMap,
        }),
      });
    });

    await openSlotInspectorEditor(page, 8, 0, assignment);
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await page.locator('#inspector-save').click();

    await expect(page.locator('#save-dialog-container')).toHaveAttribute('aria-hidden', 'true');
    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    expect(postPayloads).toHaveLength(1);
    expect(postPayloads[0]?.notify).toBe(true);
    expect(postPayloads[0]?.diffs).toHaveLength(1);

    await expect(page.locator('#review-pending')).toBeDisabled();
    await expect(page.locator('#review-pending')).toContainText('Review pending');
  });

  test('should review and apply pending changes with notifications toggled off', async ({ page }) => {
    const start = scopedFutureStart('2035-02-03');
    await openFutureBlankDeviceGrid(page, '2035-02-03');
    const assignment = await pickSchedulableAssignment(page);
    test.skip(!assignment, 'No schedulable group/member assignment is available in this fixture.');

    const postPayloads: Array<{ diffs: unknown[]; notify: boolean }> = [];
    await page.route('**/device/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      const raw = request.postData() ?? '{}';
      const parsed = JSON.parse(raw);
      const payload = parsed?.payload ?? {};
      const diffs = Array.isArray(payload.diffs)
        ? (payload.diffs as Array<{ id?: string }>)
        : [];
      postPayloads.push({ diffs, notify: Boolean(payload.notify) });
      const idMap = Object.fromEntries(
        diffs
          .filter((diff) => typeof diff.id === 'string' && diff.id.startsWith('new-'))
          .map((diff, index) => [diff.id, 9100 + index])
      );
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          saved: diffs.length,
          notifications: [],
          id_map: idMap,
        }),
      });
    });

    await editSlotThroughInspector(page, 8, 0, assignment);
    await editSlotThroughInspector(page, 10, 1, assignment);
    await expect(page.locator('#review-pending')).toContainText('Review pending');

    await page.locator('#review-pending').click();
    const saveDialog = page.locator('#save-dialog-container .dialog-box-container');
    await expect(saveDialog).toBeVisible();
    await expect(saveDialog).toContainText(start);
    await expect(saveDialog).toContainText(jumpDay(start, 1));
    await page.locator('#send-notifications').uncheck();
    await page.locator('#save-dialog-container button[name="confirm"]').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/2 entries updated/i);
    expect(postPayloads).toHaveLength(1);
    expect(postPayloads[0]?.notify).toBe(false);
    expect(postPayloads[0]?.diffs).toHaveLength(2);
    await expect(page.locator('#review-pending')).toBeDisabled();
    await expect(page.locator('#review-pending')).toContainText('Review pending');

    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();
  });

  test('should keep unsaved multi-slot draft edits visible after closing the inspector', async ({ page }) => {
    await openFutureBlankDeviceGrid(page, '2035-02-05');
    const assignment = await pickSchedulableAssignment(page);
    test.skip(!assignment, 'No schedulable group/member assignment is available in this fixture.');

    const { dialog, slotEditor } = await openSlotInspectorEditor(page, 8, 0, assignment);
    await expect(slotEditor.locator('input[id^="grp-"]').first()).toHaveValue(assignment.group);
    await page.locator('#inspector-end-slot').selectOption('2');
    await expect(page.locator('#inspector-preview-count')).toContainText('2 slots');
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await expect(dialog).toContainText('2 changes');

    await page.locator('#inspector-exit').click();
    await expect(dialog).not.toBeVisible();

    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await expect
      .poll(async () => await page.locator('entry-cell[data-changed="true"]').count(), { timeout: 10000 })
      .toBe(2);
  });

  test('should mirror invalid assignment validation into the inspector editor', async ({ page }) => {
    await openFutureBlankDeviceGrid(page, '2035-02-06');
    const { dialog, slotEditor } = await openSlotInspectorEditor(page, 8, 0, {
      group: 'NOTREAL',
      member: 'ghost',
    });

    await expect(dialog).toContainText('2 errors');
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await expect
      .poll(async () =>
        slotEditor.locator('input[id^="grp-"]').first().evaluate((el) => el.validationMessage)
      )
      .toContain('invalid');
    await expect
      .poll(async () =>
        slotEditor.locator('input[id^="mem-"]').first().evaluate((el) => el.validationMessage)
      )
      .toContain('invalid');
  });

  test('should invalidate a stale member when the group changes', async ({ page }) => {
    const { assignment } = await openFutureBlankSchedulableDeviceGrid(page, '2035-02-06');

    const { dialog, slotEditor } = await openSlotInspectorEditor(page, 8, 0, assignment);
    await slotEditor.locator('input[id^="grp-"]').first().fill('');

    await expect(dialog).toContainText('1 error');
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await expect
      .poll(async () =>
        slotEditor.locator('input[id^="mem-"]').first().evaluate((el) => ({
          valid: el.validity.valid,
          message: el.validationMessage,
        }))
      )
      .toEqual(
        expect.objectContaining({
          valid: false,
          message: expect.stringContaining('invalid'),
        })
      );
  });

  test('should allow clearing a saved assignment back to open', async ({ page }) => {
    const { assignment } = await openFutureBlankSchedulableDeviceGrid(page, '2035-02-08');
    const postPayloads: Array<{ diffs: unknown[]; notify: boolean }> = [];
    await page.route('**/device/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      const raw = request.postData() ?? '{}';
      const parsed = JSON.parse(raw);
      const payload = parsed?.payload ?? {};
      const diffs = Array.isArray(payload.diffs)
        ? (payload.diffs as Array<{ id?: string }>)
        : [];
      postPayloads.push({ diffs, notify: Boolean(payload.notify) });
      const idMap = Object.fromEntries(
        diffs
          .filter((diff) => typeof diff.id === 'string' && diff.id.startsWith('new-'))
          .map((diff, index) => [diff.id, 9200 + index])
      );
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          saved: diffs.length,
          notifications: [],
          id_map: idMap,
        }),
      });
    });

    const { cell, dialog, slotEditor } = await openSlotInspectorEditor(page, 8, 0, assignment);
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await page.locator('#inspector-save').click();
    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    expect(postPayloads).toHaveLength(1);
    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();

    await cell.dblclick();
    await expect(dialog).toBeVisible();

    const groupInput = slotEditor.locator('input[id^="grp-"]').first();
    const memberInput = slotEditor.locator('input[id^="mem-"]').first();
    await groupInput.fill('');
    await memberInput.fill('');

    await expect(dialog).toContainText('0 errors');
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await expect(page.locator('#review-pending')).not.toContainText('error');
    await expect
      .poll(async () =>
        memberInput.evaluate((el) => ({
          valid: el.validity.valid,
          message: el.validationMessage,
        }))
      )
      .toEqual({
        valid: true,
        message: '',
      });
  });

  test('should reset multi-slot duration when opening a different slot after save', async ({ page }) => {
    const { assignment } = await openFutureBlankSchedulableDeviceGrid(page, '2035-02-09');
    await page.route('**/device/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      const raw = request.postData() ?? '{}';
      const parsed = JSON.parse(raw);
      const payload = parsed?.payload ?? {};
      const diffs = Array.isArray(payload.diffs)
        ? (payload.diffs as Array<{ id?: string }>)
        : [];
      const idMap = Object.fromEntries(
        diffs
          .filter((diff) => typeof diff.id === 'string' && diff.id.startsWith('new-'))
          .map((diff, index) => [diff.id, 9300 + index])
      );
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          saved: diffs.length,
          notifications: [],
          id_map: idMap,
        }),
      });
    });

    const { dialog } = await openSlotInspectorEditor(page, 8, 0, assignment);
    await expect(page.locator('#inspector-end-slot')).toHaveValue('1');
    await page.locator('#inspector-end-slot').selectOption('3');
    await expect(page.locator('#inspector-preview-count')).toContainText('3 slots');

    await page.locator('#inspector-save').click();
    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();

    const nextCell = page.locator('#row-12 td').first();
    await nextCell.dblclick();
    await expect(dialog).toBeVisible();
    await expect(page.locator('#inspector-end-slot')).toHaveValue('1');
    await expect(page.locator('#inspector-preview-count')).toContainText('1 slot');
  });

  test('should reset multi-slot duration when reopening the same slot after save', async ({
    page,
  }) => {
    const { assignment } = await openFutureBlankSchedulableDeviceGrid(page, '2035-02-09');
    await page.route('**/device/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      const raw = request.postData() ?? '{}';
      const parsed = JSON.parse(raw);
      const payload = parsed?.payload ?? {};
      const diffs = Array.isArray(payload.diffs)
        ? (payload.diffs as Array<{ id?: string }>)
        : [];
      const idMap = Object.fromEntries(
        diffs
          .filter((diff) => typeof diff.id === 'string' && diff.id.startsWith('new-'))
          .map((diff, index) => [diff.id, 9400 + index])
      );
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          saved: diffs.length,
          notifications: [],
          id_map: idMap,
        }),
      });
    });

    const { dialog, cell } = await openSlotInspectorEditor(page, 8, 0, assignment);
    await expect(page.locator('#inspector-end-slot')).toHaveValue('1');
    await page.locator('#inspector-end-slot').selectOption('3');
    await expect(page.locator('#inspector-preview-count')).toContainText('3 slots');

    await page.locator('#inspector-save').click();
    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();

    await cell.dblclick();
    await expect(dialog).toBeVisible();
    await expect(page.locator('#inspector-end-slot')).toHaveValue('1');
    await expect(page.locator('#inspector-preview-count')).toContainText('1 slot');
  });

  test('should submit pending review changes when confirm is pressed', async ({ page }) => {
    await openFutureBlankDeviceGrid(page, '2035-02-07');
    const assignment = await pickSchedulableAssignment(page);
    test.skip(!assignment, 'No schedulable group/member assignment is available in this fixture.');

    const { dialog } = await openSlotInspectorEditor(page, 8, 0, assignment);
    await page.locator('#inspector-exit').click();
    await expect(dialog).not.toBeVisible();

    await page.locator('#review-pending').click();
    const saveDialog = page.locator('#save-dialog-container .dialog-box-container');
    await expect(saveDialog).toBeVisible();
    await page.locator('#save-dialog-container button[name="confirm"]').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect
      .poll(async () => await page.locator('#review-pending').textContent(), { timeout: 10000 })
      .toContain('Review pending');
  });

  test('should submit multi-entry pending review changes when confirm is pressed', async ({ page }) => {
    const { assignment } = await openFutureBlankSchedulableDeviceGrid(page, '2035-02-10');
    const postPayloads: Array<{ diffs: unknown[]; notify: boolean }> = [];
    await page.route('**/device/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      const raw = request.postData() ?? '{}';
      const parsed = JSON.parse(raw);
      const payload = parsed?.payload ?? {};
      const diffs = Array.isArray(payload.diffs)
        ? (payload.diffs as Array<{ id?: string }>)
        : [];
      postPayloads.push({ diffs, notify: Boolean(payload.notify) });
      const idMap = Object.fromEntries(
        diffs
          .filter((diff) => typeof diff.id === 'string' && diff.id.startsWith('new-'))
          .map((diff, index) => [diff.id, 9400 + index])
      );
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          saved: diffs.length,
          notifications: [],
          id_map: idMap,
        }),
      });
    });

    const noonEditor = await openSlotInspectorEditor(page, 12, 0, assignment);
    await page.locator('#inspector-exit').click();
    await expect(noonEditor.dialog).not.toBeVisible();

    const onePmEditor = await openSlotInspectorEditor(page, 13, 0, assignment);
    await onePmEditor.slotEditor.locator('input[id^="tech-requested-"]').first().check();
    await page.locator('#inspector-exit').click();
    await expect(onePmEditor.dialog).not.toBeVisible();

    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await page.locator('#review-pending').click();
    const saveDialog = page.locator('#save-dialog-container .dialog-box-container');
    await expect(saveDialog).toBeVisible();
    await page.locator('#save-dialog-container button[name="confirm"]').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/2 entries updated/i);
    expect(postPayloads).toHaveLength(1);
    expect(postPayloads[0]?.diffs).toHaveLength(2);
    await expect
      .poll(async () => await page.locator('#review-pending').textContent(), { timeout: 10000 })
      .toContain('Review pending');
  });

  test('should confirm selected clean review changes and reopen issue rows for repair', async ({
    page,
  }) => {
    await openFutureBlankDeviceGrid(page, '2035-02-14');
    const assignment = await pickSchedulableAssignment(page);
    test.skip(!assignment, 'No schedulable group/member assignment is available in this fixture.');

    const postPayloads: Array<{ diffs: unknown[]; notify: boolean }> = [];
    await page.route('**/device/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      const raw = request.postData() ?? '{}';
      const parsed = JSON.parse(raw);
      const payload = parsed?.payload ?? {};
      const diffs = Array.isArray(payload.diffs)
        ? (payload.diffs as Array<{ id?: string }>)
        : [];
      postPayloads.push({ diffs, notify: Boolean(payload.notify) });
      const idMap = Object.fromEntries(
        diffs
          .filter((diff) => typeof diff.id === 'string' && diff.id.startsWith('new-'))
          .map((diff, index) => [diff.id, 9450 + index])
      );
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          saved: diffs.length,
          notifications: [],
          id_map: idMap,
        }),
      });
    });

    await editSlotThroughInspector(page, 8, 0, assignment);
    const invalidEditor = await openSlotInspectorEditor(page, 10, 0, {
      group: 'NOTREAL',
      member: 'ghost',
    });
    await expect(invalidEditor.dialog).toContainText(/error/i);
    await page.locator('#inspector-exit').click();
    await expect(invalidEditor.dialog).not.toBeVisible();

    await page.locator('#review-pending').click();
    const saveDialog = page.locator('#save-dialog-container .dialog-box-container');
    await expect(saveDialog).toBeVisible();

    const confirmButton = page.locator('#save-dialog-container button[name="confirm"]');
    const reviewToggle = saveDialog.locator('.review-item-checkbox').first();
    await expect(reviewToggle).toBeChecked();
    await expect(confirmButton).toBeEnabled();
    await reviewToggle.uncheck();
    await expect(confirmButton).toBeDisabled();
    await reviewToggle.check();
    await expect(confirmButton).toBeEnabled();

    await saveDialog.locator('.review-item-issue .review-item-action').first().click();
    const detailsDialog = page.locator('#inspector-dialog-container .dialog-box-container');
    await expect(detailsDialog).toBeVisible();
    await expect(saveDialog).toBeVisible();
    await expect(
      detailsDialog.locator('.editor-inspector-detail-errors')
    ).not.toHaveText('0 errors');
    await page.locator('#inspector-exit').click();
    await expect(detailsDialog).not.toBeVisible();
    await expect(saveDialog).toBeVisible();
    await page.locator('#save-dialog-container button[name="confirm"]').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    expect(postPayloads).toHaveLength(1);
    expect(postPayloads[0]?.diffs).toHaveLength(1);

    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await expect(page.locator('#review-pending')).not.toBeDisabled();
  });

  test('should keep failed slots pending during partial multi-slot saves', async ({ page }) => {
    const { assignment } = await openFutureBlankSchedulableDeviceGrid(page, '2035-02-17');
    const postPayloads: Array<{ diffs: Array<{ id?: string }>; notify: boolean }> = [];
    await page.route('**/device/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      const raw = request.postData() ?? '{}';
      const parsed = JSON.parse(raw);
      const payload = parsed?.payload ?? {};
      const diffs = Array.isArray(payload.diffs)
        ? (payload.diffs as Array<{ id?: string }>)
        : [];
      postPayloads.push({ diffs, notify: Boolean(payload.notify) });
      const first = diffs[0];
      const second = diffs[1];
      const idMap =
        typeof first?.id === 'string' && first.id.startsWith('new-') ? { [first.id]: 9500 } : {};
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          saved: 1,
          notifications: [],
          id_map: idMap,
          errors:
            typeof second?.id === 'string'
              ? {
                  [second.id]: [{ source: 'member', message: 'simulated partial failure' }],
                }
              : {},
        }),
      });
    });

    const { dialog } = await openSlotInspectorEditor(page, 12, 0, assignment);
    await page.locator('#inspector-end-slot').selectOption('2');
    await expect(page.locator('#inspector-preview-count')).toContainText('2 slots');

    await page.locator('#inspector-save').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    await expect(resultDialog).toContainText('simulated partial failure');
    expect(postPayloads).toHaveLength(1);
    expect(postPayloads[0]?.diffs).toHaveLength(2);

    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(dialog).toBeVisible();
    await expect(page.locator('#review-pending')).toContainText('Review pending');
  });

  test('should surface array-style server save errors without fake slot failures', async ({ page }) => {
    const { assignment } = await openFutureBlankSchedulableDeviceGrid(page, '2035-02-11');
    let postCount = 0;
    await page.route('**/device/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      postCount += 1;
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          errors: ['synthetic failure for scheduler UX check'],
        }),
      });
    });

    const { dialog } = await openSlotInspectorEditor(page, 12, 0, assignment);
    await expect(dialog).toBeVisible();

    await page.locator('#inspector-save').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText('synthetic failure for scheduler UX check');
    await expect(resultDialog).not.toContainText('entry 0');
    await expect(resultDialog).not.toContainText('entry not loaded in current view');
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    expect(postCount).toBe(1);
  });

  test('should allow retrying stale-write conflicts from the same pending draft', async ({ page }) => {
    const { assignment } = await openFutureBlankSchedulableDeviceGrid(page, '2035-02-12');
    const conflictGroup = await page.evaluate((currentGroup) => {
      const groups = document.getElementById('groups');
      if (!(groups instanceof HTMLDataListElement)) {
        return null;
      }
      return [...groups.options]
        .map((option) => option.value.trim())
        .find((value) => value !== '' && value !== currentGroup);
    }, assignment.group);
    test.skip(!conflictGroup, 'No alternate schedulable group is available in this fixture.');

    const postPayloads: Array<{
      diffs: Array<{ id?: string; group?: [string, string] }>;
      notify: boolean;
    }> = [];
    let postCount = 0;
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
        ? (payload.diffs as Array<{ id?: string; group?: [string, string] }>)
        : [];
      postPayloads.push({ diffs, notify: Boolean(payload.notify) });
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
                        key: 'group',
                        expected: conflictGroup,
                        got: '',
                      },
                    ],
                  }
                : {},
          }),
        });
        return;
      }
      const idMap = Object.fromEntries(
        diffs
          .filter((diff) => typeof diff.id === 'string' && diff.id.startsWith('new-'))
          .map((diff, index) => [diff.id, 9600 + index])
      );
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          saved: diffs.length,
          notifications: [],
          id_map: idMap,
        }),
      });
    });

    const { dialog, slotEditor } = await openSlotInspectorEditor(page, 8, 0, {
      group: '',
      member: '',
    });
    await slotEditor.locator('input[id^="grp-"]').first().fill(assignment.group);
    await expect(page.locator('#review-pending')).toContainText('Review pending');

    await page.locator('#inspector-save').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/overwritten by another user/i);
    expect(postPayloads).toHaveLength(1);
    expect(postPayloads[0]?.diffs[0]?.group).toEqual(['', assignment.group]);

    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();
    await expect(dialog).toBeVisible();
    await expect(page.locator('#review-pending')).toContainText('Review pending');
    await expect(page.locator('#review-pending')).not.toContainText('error');

    await page.locator('#inspector-save').click();

    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    expect(postCount).toBe(2);
    expect(postPayloads).toHaveLength(2);
    expect(postPayloads[1]?.diffs[0]?.group).toEqual([conflictGroup, assignment.group]);
  });
});
