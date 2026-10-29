import { expect, test } from '../support/auth-fixture';
import { openSeededDeviceGrid } from '../utils/device-grid';
import {
  grantDeviceSupportPermission,
  isMockMode,
  openFutureBlankDeviceGrid,
  openFutureDeviceGrid,
  openSlotInspectorEditor,
} from '../utils/device-ui-interactions';

test.describe('Schedule UI interactions', () => {
  test.skip(!isMockMode, 'Schedule editor interactions require mock fixtures.');
  test.setTimeout(90000);

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

  test('should use a compact date picker and focused legend copy', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    await page.setViewportSize({ width: 760, height: 900 });
    const jumpForm = page.locator('nav.jump-form');
    const startInput = jumpForm.locator('input[name="start"]');
    await expect(startInput).toHaveAttribute('type', 'date');
    await expect(page.locator('#jump-open-picker')).toBeVisible();
    await expect(page.locator('#jump-prev-non-empty')).toContainText('Prev scheduled');
    await expect(page.locator('#jump-next-non-empty')).toContainText('Next scheduled');
    const prevBox = await page.locator('#jump-prev-non-empty').boundingBox();
    const nextBox = await page.locator('#jump-next-non-empty').boundingBox();
    expect(prevBox).not.toBeNull();
    expect(nextBox).not.toBeNull();
    if (prevBox && nextBox) {
      expect(Math.abs(prevBox.y - nextBox.y)).toBeLessThan(4);
    }

    await page.locator('#legend-open').click();
    const legendDialog = page.locator('#legend-dialog-container .dialog-box-container');
    await expect(legendDialog).toContainText('How To Read This Schedule');
    await expect(legendDialog).toContainText('You have unsaved edits for this slot.');
    await expect(legendDialog).toContainText('The server rejected the last save for this slot.');
    await expect(legendDialog).toContainText('The left stripe shows the assigned group color.');
    await expect(legendDialog).toContainText('Muted rows are outside the normal 7am to 10pm window.');
    await expect(legendDialog).not.toContainText('status markers');
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
    await expect(page.locator('.editor-inspector #inspector-open')).toContainText(/details/i);
    await expect(page.locator('#review-pending')).toContainText(/review pending/i);
    await expect(page.locator('#review-pending')).toBeDisabled();
    await expect(page.locator('#inspector-save')).toHaveCount(1);
  });

  test('shows no read-only cue for an editable future slot', async ({ page }) => {
    await openFutureBlankDeviceGrid(page, '2035-02-08');

    const cell = page.locator('#row-8 td').nth(0);
    await cell.dblclick();

    const dialog = page.locator('#inspector-dialog-container .dialog-box-container');
    await expect(dialog).toBeVisible();
    await expect(cell.locator('[data-readonly-cue="slot"]')).toHaveAttribute('hidden', '');
    await expect(cell.locator('[data-support-cue="slot"]')).toHaveAttribute('hidden', '');
    await expect(cell.locator('.time-use-icon .status-token-unrecorded')).toHaveCount(0);
    await expect(page.locator('#inspector-open [data-readonly-cue="selection"]')).toHaveAttribute('hidden', '');
    await expect(page.locator('#inspector-open [data-support-cue="selection"]')).toHaveAttribute('hidden', '');
  });

  test('shows support cues for a selected slot with actionable support', async ({ page }) => {
    await grantDeviceSupportPermission(page, 'd', 'medical');
    await openFutureDeviceGrid(page, 'd', '2035-03-18');

    const { cell, dialog, slotEditor } = await openSlotInspectorEditor(page, 8, 0, {
      group: 'BEI',
      member: 'user0048',
    });
    await slotEditor.locator('input[id^="med-requested-"]').first().check();

    await expect(dialog).toBeVisible();
    await expect(cell.locator('[data-support-cue="slot"]')).toBeVisible();
    await expect(page.locator('#inspector-open [data-support-cue="selection"]')).toBeVisible();
    await expect(cell.locator('[data-readonly-cue="slot"]')).toHaveAttribute('hidden', '');
  });

  test.describe('read-only slot cues', () => {
    test.use({ authProfile: 'member' });

    test('shows lock cues for a selected read-only slot', async ({ page }) => {
      const { path } = await openSeededDeviceGrid(page);
      expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

      const cell = page.locator('.editor #scroll-container entry-cell').first();
      await expect(cell).toBeVisible();
      await cell.dblclick();

      const dialog = page.locator('#inspector-dialog-container .dialog-box-container');
      await expect(dialog).toBeVisible();
      await expect(cell.locator('[data-readonly-cue="slot"]')).toBeVisible();
      await expect(page.locator('#inspector-open [data-readonly-cue="selection"]')).toBeVisible();
    });

    test('keeps lock cues visible after shifting the read-only day window', async ({ page }) => {
      const { path } = await openSeededDeviceGrid(page);
      expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

      const firstHeader = page.locator('.editor #scroll-container thead th').nth(1);
      const initialHeader = (await firstHeader.textContent())?.trim() ?? '';
      await expect(initialHeader).not.toBe('');

      await page.locator('#scroll-next-day').click();
      await expect
        .poll(async () => ((await firstHeader.textContent()) ?? '').trim(), { timeout: 15000 })
        .not.toBe(initialHeader);

      await expect
        .poll(
          async () =>
            await page.evaluate(() => {
              const row = document.querySelector('#row-8');
              if (!row) {
                return -1;
              }
              const entries = [...row.querySelectorAll('entry-cell')];
              if (entries.length === 0) {
                return -1;
              }
              return entries.filter((entry) => {
                if (entry.getAttribute('data-booking-editable') === 'true') {
                  return false;
                }
                return (
                  entry
                    .querySelector('[data-readonly-cue="slot"]')
                    ?.hasAttribute('hidden') ?? true
                );
              }).length;
            }),
          { timeout: 15000 }
        )
        .toBe(0);
    });
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
});
