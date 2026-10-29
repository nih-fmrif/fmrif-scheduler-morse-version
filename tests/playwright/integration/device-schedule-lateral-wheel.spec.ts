import { expect, test } from '../support/auth-fixture';
import { openSeededDeviceGrid } from '../utils/device-grid';
import {
  isMockMode,
  placeholderCount,
  statusText,
  timeslotLabelWidth,
  visibleDayColumnWidth,
  visibleHeaderCoverage,
  waitForAllRowsReady,
} from '../utils/device-schedule-lateral';

test.describe('Schedule lateral navigation contract', () => {
  test.skip(!isMockMode, 'Schedule editor interactions require mock fixtures.');
  test.setTimeout(90000);

  test('wheel scanning keeps rendered cells until movement crosses half a column', async ({
    page,
  }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);
    await waitForAllRowsReady(page);
    await page.setViewportSize({ width: 640, height: 920 });
    const compactUrl = new URL(page.url());
    compactUrl.searchParams.set('days', '2');
    await page.goto(compactUrl.toString());
    await waitForAllRowsReady(page);

    const container = page.locator('.editor #scroll-container');
    await expect(container).toBeVisible();

    const colWidth = await visibleDayColumnWidth(page);
    expect(colWidth).toBeGreaterThan(0);

    const subThresholdDelta = Math.max(1, Math.floor(colWidth * 0.75));
    const thresholdCrossingDelta = Math.max(1, Math.ceil(colWidth * 0.4));
    const renderedBefore = await page.locator('.editor #scroll-container td entry-cell').count();
    expect(renderedBefore).toBeGreaterThan(0);

    await container.evaluate((node, deltaX) => {
      const event = new WheelEvent('wheel', {
        deltaX,
        deltaY: 0,
        bubbles: true,
        cancelable: true,
      });
      node.dispatchEvent(event);
    }, subThresholdDelta);

    await page.waitForTimeout(60);
    await expect.poll(async () => await placeholderCount(page), { timeout: 1000 }).toBe(0);
    expect(await page.locator('.editor #scroll-container td entry-cell').count()).toBeGreaterThan(0);

    await container.evaluate((node, deltaX) => {
      const event = new WheelEvent('wheel', {
        deltaX,
        deltaY: 0,
        bubbles: true,
        cancelable: true,
      });
      node.dispatchEvent(event);
    }, thresholdCrossingDelta);

    await expect.poll(async () => await placeholderCount(page), { timeout: 3000 }).toBeGreaterThan(0);
  });

  test('wheel scanning shows placeholders during movement and hydrates on settle', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);
    await waitForAllRowsReady(page);
    await page.setViewportSize({ width: 640, height: 920 });
    const compactUrl = new URL(page.url());
    compactUrl.searchParams.set('days', '2');
    await page.goto(compactUrl.toString());
    await waitForAllRowsReady(page);

    const container = page.locator('.editor #scroll-container');
    await expect(container).toBeVisible();

    const urlBefore = new URL(page.url());
    const startBefore = urlBefore.searchParams.get('start') ?? '';
    const daysBefore = urlBefore.searchParams.get('days') ?? '7';
    const historyBefore = await page.evaluate(() => window.history.length);
    const navCountBefore = await page.evaluate(() => performance.getEntriesByType('navigation').length);
    const labelWidthBefore = await timeslotLabelWidth(page);

    const defaultPrevented = await container.evaluate((node) => {
      const event = new WheelEvent('wheel', {
        deltaX: 520,
        deltaY: 0,
        bubbles: true,
        cancelable: true,
      });
      node.dispatchEvent(event);
      return event.defaultPrevented;
    });
    expect(defaultPrevented).toBe(true);

    await expect.poll(async () => await placeholderCount(page), { timeout: 3000 }).toBeGreaterThan(0);
    const movingHeaderCount = await page
      .locator('.editor #scroll-container thead th')
      .evaluateAll((cells) => cells.filter((cell) => !cell.hidden).length);
    expect(movingHeaderCount).toBeGreaterThanOrEqual(4);
    expect(await visibleHeaderCoverage(page)).toBeGreaterThan(0.95);
    const labelWidthDuring = await timeslotLabelWidth(page);
    expect(Math.abs(labelWidthDuring - labelWidthBefore)).toBeLessThan(2.5);
    await expect
      .poll(async () => (await statusText(page)).toLowerCase(), { timeout: 3000 })
      .toContain('scanning: waiting for pause');

    await page.waitForTimeout(450);
    await expect.poll(async () => await placeholderCount(page), { timeout: 5000 }).toBe(0);

    const urlAfter = new URL(page.url());
    expect(urlAfter.searchParams.get('start')).not.toBe(startBefore);
    expect(urlAfter.searchParams.get('days') ?? '7').toBe(daysBefore);
    const historyAfter = await page.evaluate(() => window.history.length);
    expect(historyAfter).toBe(historyBefore);
    const navCountAfter = await page.evaluate(() => performance.getEntriesByType('navigation').length);
    expect(navCountAfter).toBe(navCountBefore);
  });

  test('one-day wheel scanning keeps timeslot label width stable', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);
    await waitForAllRowsReady(page);
    await page.setViewportSize({ width: 560, height: 920 });
    const oneDayUrl = new URL(page.url());
    oneDayUrl.searchParams.set('days', '1');
    await page.goto(oneDayUrl.toString());
    await waitForAllRowsReady(page);

    const container = page.locator('.editor #scroll-container');
    await expect(container).toBeVisible();
    const widthBefore = await timeslotLabelWidth(page);
    expect(widthBefore).toBeGreaterThan(40);
    expect(widthBefore).toBeLessThan(110);

    const defaultPrevented = await container.evaluate((node) => {
      const event = new WheelEvent('wheel', {
        deltaX: 640,
        deltaY: 0,
        bubbles: true,
        cancelable: true,
      });
      node.dispatchEvent(event);
      return event.defaultPrevented;
    });
    expect(defaultPrevented).toBe(true);

    await expect.poll(async () => await placeholderCount(page), { timeout: 3000 }).toBeGreaterThan(0);
    const widthDuring = await timeslotLabelWidth(page);
    expect(widthDuring).toBeGreaterThan(40);
    expect(widthDuring).toBeLessThan(110);
    expect(Math.abs(widthDuring - widthBefore)).toBeLessThan(1.5);

    await page.waitForTimeout(450);
    await expect.poll(async () => await placeholderCount(page), { timeout: 5000 }).toBe(0);
  });
});
