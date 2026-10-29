import type { Page } from '@playwright/test';

import { expect, test } from '../support/auth-fixture';

import { openSeededDeviceGrid } from '../utils/device-grid';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

function ymd(date: Date) {
  return date.toISOString().slice(0, 10);
}

function jumpDay(start: string, deltaDays: number) {
  const value = new Date(`${start}T00:00:00.000Z`);
  return ymd(new Date(value.getTime() + deltaDays * 24 * 60 * 60 * 1000));
}

async function openFutureBlankDeviceGrid(page: Page, start = '2035-02-01') {
  await openSeededDeviceGrid(page);
  const url = new URL(page.url());
  url.searchParams.set('start', start);
  url.searchParams.set('days', '2');
  await page.goto(url.toString());
  await expect(page.locator('.editor #scroll-container')).toBeVisible();
  await expect
    .poll(async () => await page.locator('#row-8 entry-cell').count(), { timeout: 15000 })
    .toBeGreaterThan(0);
  await expect
    .poll(async () => await page.locator('#row-10 entry-cell').count(), { timeout: 15000 })
    .toBeGreaterThan(0);
}

async function openFutureBlankSchedulableDeviceGrid(page: Page, start = '2035-02-01') {
  await page.goto('/');
  const devicePaths = await page
    .locator('[data-home-section="devices"] a.list-card[href^="/device/"]')
    .evaluateAll((links) =>
      [...new Set(links.map((link) => link.getAttribute('href')).filter((href): href is string => !!href))]
    );

  for (const devicePath of devicePaths) {
    const url = new URL(devicePath, page.url());
    url.searchParams.set('start', start);
    url.searchParams.set('days', '2');
    await page.goto(url.toString());

    const container = page.locator('.editor #scroll-container');
    if ((await container.count()) === 0) {
      continue;
    }

    await expect(container).toBeVisible();
    await expect.poll(async () => await page.locator('#row-8 entry-cell').count(), { timeout: 15000 }).toBeGreaterThan(0);

    const assignment = await pickSchedulableAssignment(page);
    if (assignment) {
      return { assignment };
    }
  }

  throw new Error('No schedulable future device grid was available in the seeded fixture set.');
}

async function openFutureDeviceGrid(page: Page, device: string, start = '2035-02-01') {
  await page.goto(`/device/${device}?start=${start}&days=2`);
  await expect(page.locator('.editor #scroll-container')).toBeVisible();
  await expect.poll(async () => await page.locator('#row-8 entry-cell').count(), { timeout: 15000 }).toBeGreaterThan(0);
}

async function grantDeviceSupportPermission(
  page: Page,
  device: string,
  permission: 'medical' | 'training'
) {
  await page.goto(`/rbac?scope=device&entity=${device}`);
  await expect(page.getByRole('status')).toContainText('Relationships loaded.');

  const section = page.locator('article.rbac-matrix').filter({
    has: page.getByRole('heading', { name: 'DEV user permissions' }),
  });
  await expect(section).toBeVisible();

  const row = section.locator('tbody tr').filter({ hasText: 'user0049' }).first();
  await expect(row).toBeVisible();

  const checkboxIndex = permission === 'medical' ? 3 : 4;
  const checkbox = row.locator('input[type="checkbox"]').nth(checkboxIndex);
  if (await checkbox.isChecked()) {
    return;
  }

  const confirmPromise = page.waitForEvent('dialog');
  await checkbox.check();
  await section.getByRole('button', { name: /apply permission updates/i }).click();
  const confirm = await confirmPromise;
  await confirm.accept();
  await expect(section.getByRole('button', { name: /apply permission updates/i })).toBeDisabled();
}

async function pickSchedulableAssignment(page: Page) {
  return page.evaluate(() => {
    const groups = document.getElementById('groups');
    if (!(groups instanceof HTMLDataListElement)) {
      return null;
    }
    for (const option of [...groups.options]) {
      const group = option.value.trim();
      if (!group) {
        continue;
      }
      const members = document.getElementById(`members-of-${group}`);
      if (!(members instanceof HTMLDataListElement)) {
        continue;
      }
      const member = [...members.options]
        .map((entry) => entry.value.trim())
        .find((value) => value !== '');
      if (member) {
        return { group, member };
      }
    }
    return null;
  });
}

async function editSlotThroughInspector(
  page: Page,
  hour: number,
  colIndex: number,
  assignment: { group: string; member: string }
) {
  const row = page.locator(`#row-${hour}`);
  await row.scrollIntoViewIfNeeded();
  await expect.poll(async () => await row.locator('entry-cell').count(), { timeout: 10000 }).toBeGreaterThan(0);

  const cell = row.locator('td').nth(colIndex);
  await cell.dblclick();

  const dialog = page.locator('#inspector-dialog-container .dialog-box-container');
  await expect(dialog).toBeVisible();

  const slotEditor = page.locator('#inspector-slot-editor');
  await slotEditor.locator('input[id^="grp-"]').first().fill(assignment.group);
  await slotEditor.locator('input[id^="mem-"]').first().fill(assignment.member);
  await page.locator('#inspector-exit').click();
  await expect(dialog).not.toBeVisible();
}

async function openSlotInspectorEditor(
  page: Page,
  hour: number,
  colIndex: number,
  assignment: { group: string; member: string }
) {
  const row = page.locator(`#row-${hour}`);
  await row.scrollIntoViewIfNeeded();
  await expect.poll(async () => await row.locator('entry-cell').count(), { timeout: 10000 }).toBeGreaterThan(0);

  const cell = row.locator('td').nth(colIndex);
  await cell.dblclick();

  const dialog = page.locator('#inspector-dialog-container .dialog-box-container');
  await expect(dialog).toBeVisible();

  const slotEditor = page.locator('#inspector-slot-editor');
  await slotEditor.locator('input[id^="grp-"]').first().fill(assignment.group);
  await slotEditor.locator('input[id^="mem-"]').first().fill(assignment.member);

  return { cell, dialog, slotEditor };
}

test.describe('Schedule UI interactions', () => {
  test.skip(!isMockMode, 'Schedule editor interactions require mock fixtures.');
  test.setTimeout(90000);

  test('requires explicit jump action before URL updates', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const jumpForm = page.locator('nav.jump-form');
    await expect(jumpForm).toBeVisible();

    const startInput = jumpForm.locator('input[name="start"]');
    const startValue = (await startInput.inputValue()).trim();
    const nextStart = jumpDay(startValue, 1);
    const urlBefore = new URL(page.url());

    await startInput.fill(nextStart);
    await page.waitForTimeout(900);
    const urlAfter = new URL(page.url());
    expect(urlAfter.searchParams.get('start')).toBe(nextStart);
    expect(urlAfter.searchParams.get('days') ?? '7').toBe(urlBefore.searchParams.get('days') ?? '7');
  });

  test('uses fallback day jump without mutating URL/history', async ({ page }) => {
    test.fail(true, 'Phase E pending: lateral fallback still mutates URL/history.');

    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const singleDayURL = new URL(page.url());
    singleDayURL.searchParams.set('days', '1');
    await page.goto(singleDayURL.toString());
    const singleDayPath = `${singleDayURL.pathname}${singleDayURL.search}`;
    expect(page.url()).toContain(singleDayPath);
    const urlBefore = new URL(page.url());
    const historyBefore = await page.evaluate(() => window.history.length);

    const configElm = page.locator('#schedule-load-config');
    const rawConfig = (await configElm.innerText()) ?? '{}';
    const config = JSON.parse(rawConfig);
    const endpointBase = new URL(config.endpoint, page.url());
    const url = new URL(page.url());
    const start = url.searchParams.get('start') ?? '';

    const scheduleNextEndpoint = endpointBase.toString().replace('/schedule-rows', '/schedule-next-day');

    const availability = await page.evaluate(
      async ({ scheduleNextEndpoint, start }) => {
        const options = { method: 'GET', headers: { Accept: 'application/json' } };
        const rightUrl = new URL(scheduleNextEndpoint);
        rightUrl.searchParams.set('start', start);
        rightUrl.searchParams.set('direction', '1');
        const leftUrl = new URL(scheduleNextEndpoint);
        leftUrl.searchParams.set('start', start);
        leftUrl.searchParams.set('direction', '-1');

        const [rightResp, leftResp] = await Promise.all([
          fetch(rightUrl.toString(), options),
          fetch(leftUrl.toString(), options),
        ]);

        const rightBody = rightResp.ok ? await rightResp.json() : null;
        const leftBody = leftResp.ok ? await leftResp.json() : null;

        return {
          right: Boolean(rightBody?.date),
          left: Boolean(leftBody?.date),
        };
      },
      { scheduleNextEndpoint, start },
    );

    const hasAdjacentWindow = availability.right;
    test.skip(!hasAdjacentWindow, 'No adjacent schedule windows available from this date.');

    const scrollContainer = page.locator('.editor #scroll-container');
    await expect(scrollContainer).toBeVisible();
    await scrollContainer.focus();

    const jumpFallback = page.waitForResponse((resp) => resp.url().includes('/schedule-next-day') && resp.request().method() === 'GET', {
      timeout: 12000,
    });
    await page.keyboard.press('ArrowRight');
    await jumpFallback;
    await page.waitForTimeout(700);
    const urlAfter = new URL(page.url());
    expect(`${urlAfter.pathname}${urlAfter.search}`).toBe(
      `${urlBefore.pathname}${urlBefore.search}`
    );
    const historyAfter = await page.evaluate(() => window.history.length);
    expect(historyAfter).toBe(historyBefore);
    await expect(page.locator('.editor table thead th')).toHaveCount(1);
  });

  test('keeps previous/next non-empty navigation in-place', async ({ page }) => {
    test.fail(true, 'Phase E pending: previous/next non-empty still mutates URL/history.');

    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const configElm = page.locator('#schedule-load-config');
    const rawConfig = (await configElm.innerText()) ?? '{}';
    const config = JSON.parse(rawConfig);
    const endpointBase = new URL(config.endpoint, page.url());
    const url = new URL(page.url());
    const start = url.searchParams.get('start') ?? '';
    const scheduleNextEndpoint = endpointBase.toString().replace('/schedule-rows', '/schedule-next-day');

    const availability = await page.evaluate(
      async ({ scheduleNextEndpoint, start }) => {
        const options = { method: 'GET', headers: { Accept: 'application/json' } };
        const rightUrl = new URL(scheduleNextEndpoint);
        rightUrl.searchParams.set('start', start);
        rightUrl.searchParams.set('direction', '1');
        const response = await fetch(rightUrl.toString(), options);
        const body = response.ok ? await response.json() : null;
        return { right: Boolean(body?.date) };
      },
      { scheduleNextEndpoint, start },
    );
    test.skip(!availability.right, 'No later non-empty day is available for this fixture.');

    const urlBefore = new URL(page.url());
    const historyBefore = await page.evaluate(() => window.history.length);
    const jumpRequest = page.waitForResponse(
      (resp) =>
        resp.url().includes('/schedule-next-day') &&
        resp.request().method() === 'GET',
      { timeout: 12000 },
    );

    await page.locator('#jump-next-non-empty').click();
    await jumpRequest;
    await page.waitForTimeout(700);

    const urlAfter = new URL(page.url());
    expect(`${urlAfter.pathname}${urlAfter.search}`).toBe(
      `${urlBefore.pathname}${urlBefore.search}`,
    );
    const historyAfter = await page.evaluate(() => window.history.length);
    expect(historyAfter).toBe(historyBefore);
  });

  test('should open and close the legend modal', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const legendButton = page.locator('#legend-open');
    await expect(legendButton).toBeVisible();
    await legendButton.click();

    const legendDialog = page.locator('#legend-dialog-container .dialog-box-container');
    await expect(legendDialog).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(legendDialog).not.toBeVisible();
  });

  test('should show a compact inspector banner', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const inspector = page.locator('.editor-inspector');
    const inspectorLine = page.locator('.editor-inspector-line');
    const workspace = page.locator('.editor-workspace');
    await expect(inspector).toBeVisible();
    await expect(inspectorLine).toBeVisible();

    const [inspectorBox, workspaceBox] = await Promise.all([
      inspector.boundingBox(),
      workspace.boundingBox(),
    ]);

    expect(inspectorBox).not.toBeNull();
    expect(workspaceBox).not.toBeNull();
    if (inspectorBox && workspaceBox) {
      expect(inspectorBox.y).toBeLessThan(workspaceBox.y + 40);
    }
  });

  test('should open inspector detail modal', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const inspectorButton = page.locator('#inspector-open');
    await expect(inspectorButton).toBeVisible();
    await inspectorButton.click();

    const inspectorDialogContainer = page.locator('#inspector-dialog-container');
    const inspectorDialog = page.locator('#inspector-dialog-container .dialog-box-container');
    await expect(inspectorDialog).toBeVisible();
    await expect(inspectorDialogContainer).toHaveAttribute('aria-hidden', 'false');

    await page.keyboard.press('Escape');
    await expect(inspectorDialog).not.toBeVisible();
    await expect(inspectorDialogContainer).toHaveAttribute('aria-hidden', 'true');
  });

  test('should expose pending review controls without restoring the old expando', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    await expect(page.locator('#expando')).toHaveCount(0);
    await expect(page.locator('.editor-inspector #inspector-open')).toContainText(/view/i);
    await expect(page.locator('#review-pending')).toContainText(/review pending/i);
    await expect(page.locator('#review-pending')).toBeDisabled();
    await expect(page.locator('#inspector-save')).toHaveCount(1);
  });

  test('should keep pending drafts after exiting the inspector', async ({ page }) => {
    await openFutureBlankDeviceGrid(page);
    const assignment = await pickSchedulableAssignment(page);
    test.skip(!assignment, 'No schedulable group/member assignment is available in this fixture.');

    await editSlotThroughInspector(page, 8, 0, assignment);
    await expect(page.locator('#review-pending')).toContainText('Review pending (1)');

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
    await expect(page.locator('#review-pending')).toContainText('Review pending (1)');
    await page.locator('#inspector-save').click();

    await expect(page.locator('#save-dialog-container')).toHaveAttribute('aria-hidden', 'true');
    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    expect(postPayloads).toHaveLength(1);
    expect(postPayloads[0]?.notify).toBe(true);
    expect(postPayloads[0]?.diffs).toHaveLength(1);

    await expect(page.locator('#review-pending')).toBeDisabled();
    await expect(page.locator('#review-pending')).toContainText('Review pending (0)');
  });

  test('should review and apply pending changes with notifications toggled off', async ({ page }) => {
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
    await expect(page.locator('#review-pending')).toContainText('Review pending (2)');

    await page.locator('#review-pending').click();
    const saveDialog = page.locator('#save-dialog-container .dialog-box-container');
    await expect(saveDialog).toBeVisible();
    await expect(saveDialog).toContainText('2035-02-03');
    await expect(saveDialog).toContainText('2035-02-04');
    await page.locator('#send-notifications').uncheck();
    await page.locator('#save-dialog-container button[name="confirm"]').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/2 entries updated/i);
    expect(postPayloads).toHaveLength(1);
    expect(postPayloads[0]?.notify).toBe(false);
    expect(postPayloads[0]?.diffs).toHaveLength(2);
    await expect(page.locator('#review-pending')).toBeDisabled();
    await expect(page.locator('#review-pending')).toContainText('Review pending (0)');

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
    await expect(page.locator('#review-pending')).toContainText('Review pending (2)');
    await expect(dialog).toContainText('2 changes');

    await page.locator('#inspector-exit').click();
    await expect(dialog).not.toBeVisible();

    await expect(page.locator('#review-pending')).toContainText('Review pending (2)');
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
    await expect(page.locator('#review-pending')).toContainText('Review pending (1, 1 error)');
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
    await expect(page.locator('#review-pending')).toContainText('Review pending (1, 1 error)');
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

  test('should enable medical support handlers when device medical permission exists', async ({ page }) => {
    await grantDeviceSupportPermission(page, 'd', 'medical');
    await openFutureDeviceGrid(page, 'd', '2035-02-18');

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
    await openFutureDeviceGrid(page, 'd', '2035-02-20');

    const initialEditor = await openSlotInspectorEditor(page, 8, 0, {
      group: 'BEI',
      member: 'user0048',
    });
    const initialRequested = initialEditor.slotEditor.locator('input[id^="med-requested-"]').first();
    const initialHandler = initialEditor.slotEditor.locator('input[id^="med-handler-"]').first();

    await initialRequested.check();
    await initialHandler.fill('user0049');
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
    await expect(reopenedEditor.slotEditor.locator('.editor-inspector-detail-summary')).toContainText(
      'no support requests'
    );
  });

  test('should allow retrying medical handler conflicts from the same draft', async ({ page }) => {
    await grantDeviceSupportPermission(page, 'd', 'medical');
    await openFutureDeviceGrid(page, 'd', '2035-02-19');

    const baseline = await openSlotInspectorEditor(page, 8, 0, {
      group: 'BEI',
      member: 'user0048',
    });
    await baseline.slotEditor.locator('input[id^="med-requested-"]').first().check();
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

    await expect(page.locator('#review-pending')).toContainText('Review pending (1)');
    await expect(page.locator('#review-pending')).not.toContainText('error');

    await page.locator('#inspector-save').click();
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);

    expect(postCount).toBe(2);
    expect(postPayloads[0]?.[0]?.med?.handler).toEqual(['', 'user0049']);
    expect(postPayloads[1]?.[0]?.med?.handler).toEqual(['user0019', 'user0049']);
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
    await expect(page.locator('#review-pending')).toContainText('Review pending (1)');
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
    await expect(page.locator('#review-pending')).toContainText('Review pending (1)');
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
      .toContain('Review pending (0)');
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

    await expect(page.locator('#review-pending')).toContainText('Review pending (2)');
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
      .toContain('Review pending (0)');
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
    await expect(page.locator('#review-pending')).toContainText('Review pending (1, 1 error)');
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
    await expect(page.locator('#review-pending')).toContainText('Review pending (1)');
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
    await expect(page.locator('#review-pending')).toContainText('Review pending (1)');

    await page.locator('#inspector-save').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/overwritten by another user/i);
    expect(postPayloads).toHaveLength(1);
    expect(postPayloads[0]?.diffs[0]?.group).toEqual(['', assignment.group]);

    await page.locator('#result-dialog-container button[data-a11y-dialog-hide]').click();
    await expect(resultDialog).not.toBeVisible();
    await expect(dialog).toBeVisible();
    await expect(page.locator('#review-pending')).toContainText('Review pending (1)');
    await expect(page.locator('#review-pending')).not.toContainText('error');

    await page.locator('#inspector-save').click();

    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    expect(postCount).toBe(2);
    expect(postPayloads).toHaveLength(2);
    expect(postPayloads[1]?.diffs[0]?.group).toEqual([conflictGroup, assignment.group]);
  });

  test('should not expand inline cell details on selection', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const container = page.locator('.editor #scroll-container');
    await expect(container).toBeVisible();
    await container.focus();

    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowDown');

    await expect(page.locator('entry-detail:visible')).toHaveCount(0);

    await page.keyboard.press('Enter');
    const inspectorDialog = page.locator('#inspector-dialog-container .dialog-box-container');
    await expect(inspectorDialog).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(inspectorDialog).not.toBeVisible();
    await expect(page.locator('entry-detail:visible')).toHaveCount(0);
  });

  test('keeps lateral wheel navigation in-place without URL/history mutation', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const container = page.locator('.editor #scroll-container');
    await expect(container).toBeVisible();

    await container.evaluate((node) => {
      node.scrollLeft = 0;
    });

    const urlBefore = new URL(page.url());
    const daysBefore = urlBefore.searchParams.get('days') ?? '7';
    const historyBefore = await page.evaluate(() => window.history.length);

    const eventResult = await container.evaluate((node) => {
      const result = {
        defaultPreventedRight: false,
        defaultPreventedLeft: false,
        movedRight: 0,
        movedLeft: 0,
        canScrollHorizontally: node.scrollWidth > node.clientWidth + 1,
      };

      node.scrollLeft = 0;
      const beforeRight = node.scrollLeft;
      const wheelRight = new WheelEvent('wheel', {
        deltaX: 220,
        bubbles: true,
        cancelable: true,
      });
      node.dispatchEvent(wheelRight);
      result.defaultPreventedRight = wheelRight.defaultPrevented;
      result.movedRight = node.scrollLeft - beforeRight;

      const maxScroll = Math.max(0, node.scrollWidth - node.clientWidth);
      node.scrollLeft = maxScroll;
      const beforeLeft = node.scrollLeft;
      const wheelLeft = new WheelEvent('wheel', {
        deltaX: -220,
        bubbles: true,
        cancelable: true,
      });
      node.dispatchEvent(wheelLeft);
      result.defaultPreventedLeft = wheelLeft.defaultPrevented;
      result.movedLeft = beforeLeft - node.scrollLeft;

      return result;
    });
    await page.waitForTimeout(900);

    const urlAfter = new URL(page.url());
    expect(urlAfter.searchParams.get('start')).toBe(urlBefore.searchParams.get('start'));
    expect(urlAfter.searchParams.get('days') ?? '7').toBe(daysBefore);
    const historyAfter = await page.evaluate(() => window.history.length);
    expect(historyAfter).toBe(historyBefore);
    expect(eventResult.defaultPreventedRight).toBe(true);
    expect(eventResult.defaultPreventedLeft).toBe(true);
    if (eventResult.canScrollHorizontally) {
      expect(eventResult.movedRight).toBeGreaterThan(0);
      expect(eventResult.movedLeft).toBeGreaterThan(0);
    } else {
      expect(eventResult.movedRight).toBe(0);
      expect(eventResult.movedLeft).toBe(0);
    }
  });

  test('should scroll laterally via edge arrow buttons', async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 720 });
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const container = page.locator('.editor #scroll-container');
    await expect(container).toBeVisible();

    const hasHorizontalOverflow = await container.evaluate((node) => {
      node.scrollLeft = 0;
      return node.scrollWidth > node.clientWidth + 1;
    });
    test.skip(!hasHorizontalOverflow, 'Grid has no horizontal overflow in this viewport.');

    const prev = page.locator('#scroll-prev-day');
    const next = page.locator('#scroll-next-day');
    await expect(prev).toBeVisible();
    await expect(next).toBeVisible();

    await expect(prev).toBeDisabled();
    await next.click();

    await expect
      .poll(async () => await container.evaluate((node) => node.scrollLeft), { timeout: 7000 })
      .toBeGreaterThan(0);

    await expect(prev).toBeEnabled();
  });

  test('should keep vertical wheel scrolling available for lower rows', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const container = page.locator('.editor #scroll-container');
    await expect(container).toBeVisible();

    const hasVerticalOverflow = await container.evaluate((node) => {
      node.scrollTop = 0;
      return node.scrollHeight > node.clientHeight + 1;
    });
    test.skip(!hasVerticalOverflow, 'Grid has no vertical overflow in this viewport.');

    await container.hover();
    await page.mouse.wheel(0, 420);

    await expect
      .poll(async () => await container.evaluate((node) => node.scrollTop), { timeout: 7000 })
      .toBeGreaterThan(0);
  });
});
