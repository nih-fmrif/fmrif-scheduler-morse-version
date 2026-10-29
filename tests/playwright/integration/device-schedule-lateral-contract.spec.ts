import type { Page } from '@playwright/test';

import { expect, test } from '../support/auth-fixture';
import { openSeededDeviceGrid } from '../utils/device-grid';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';
const PLACEHOLDER_SELECTOR = ".editor #scroll-container td[data-placeholder='true'] > .slot-placeholder";
const START_INPUT_SELECTOR = 'nav.jump-form input[name="start"]';

function ymd(date: Date) {
  return date.toISOString().slice(0, 10);
}

function addDays(start: string, deltaDays: number) {
  const value = new Date(`${start}T00:00:00.000Z`);
  return ymd(new Date(value.getTime() + deltaDays * 24 * 60 * 60 * 1000));
}

async function placeholderCount(page: Page) {
  return page.locator(PLACEHOLDER_SELECTOR).count();
}

async function statusText(page: Page) {
  return ((await page.locator('#editor-load-status').textContent()) ?? '').trim();
}

async function visibleHeaderCoverage(page: Page) {
  return page.evaluate(() => {
    const container = document.querySelector('.editor #scroll-container');
    const headerRow = container?.querySelector('thead tr');
    if (!(container instanceof HTMLElement) || !(headerRow instanceof HTMLTableRowElement)) {
      return 0;
    }
    const containerRect = container.getBoundingClientRect();
    const lead = headerRow.children[0];
    const leadWidth =
      lead instanceof HTMLElement
        ? Math.max(0, Math.round(lead.getBoundingClientRect().width))
        : 0;
    const trackStart = containerRect.left + leadWidth;
    const trackEnd = containerRect.right;
    const trackWidth = Math.max(0, trackEnd - trackStart);
    if (trackWidth <= 1) {
      return 0;
    }

    const spans = [...headerRow.querySelectorAll('th')]
      .filter((cell) => !cell.hidden)
      .map((cell) => {
        const rect = cell.getBoundingClientRect();
        const start = Math.max(trackStart, rect.left);
        const end = Math.min(trackEnd, rect.right);
        if (end <= start) {
          return null;
        }
        return [start, end] as [number, number];
      })
      .filter((span): span is [number, number] => Array.isArray(span));
    if (spans.length === 0) {
      return 0;
    }
    spans.sort((a, b) => a[0] - b[0]);
    let covered = 0;
    let cursorStart = spans[0][0];
    let cursorEnd = spans[0][1];
    for (let i = 1; i < spans.length; i += 1) {
      const [start, end] = spans[i];
      if (start <= cursorEnd) {
        cursorEnd = Math.max(cursorEnd, end);
        continue;
      }
      covered += cursorEnd - cursorStart;
      cursorStart = start;
      cursorEnd = end;
    }
    covered += cursorEnd - cursorStart;
    return covered / trackWidth;
  });
}

async function timeslotLabelWidth(page: Page) {
  return page.evaluate(() => {
    const label = document.querySelector('.editor #scroll-container tbody th');
    if (!(label instanceof HTMLElement)) {
      return 0;
    }
    return label.getBoundingClientRect().width;
  });
}

async function visibleDayColumnWidth(page: Page) {
  return page.evaluate(() => {
    const cell = [...document.querySelectorAll('.editor #scroll-container thead th')].find(
      (header): header is HTMLElement => header instanceof HTMLElement && !header.hidden
    );
    if (!(cell instanceof HTMLElement)) {
      return 0;
    }
    return cell.getBoundingClientRect().width;
  });
}

async function waitForAllRowsReady(page: Page) {
  await expect
    .poll(async () => (await statusText(page)).toLowerCase(), { timeout: 15000 })
    .toContain('all 24 rows ready');
  await expect
    .poll(async () => await placeholderCount(page), { timeout: 8000 })
    .toBe(0);
}

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

  test('day-arrow control shifts one day immediately with cache-miss skeleton fallback', async ({
    page,
  }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);
    await waitForAllRowsReady(page);

    const startInput = page.locator(START_INPUT_SELECTOR);
    const startBefore = (await startInput.inputValue()).trim();
    const expectedStart = addDays(startBefore, 1);
    const historyBefore = await page.evaluate(() => window.history.length);
    const navCountBefore = await page.evaluate(() => performance.getEntriesByType('navigation').length);

    await page.locator('#scroll-next-day').click();
    await page.waitForTimeout(60);

    expect((await statusText(page)).toLowerCase()).not.toContain('scanning');
    await expect.poll(async () => (await startInput.inputValue()).trim(), { timeout: 1000 }).toBe(expectedStart);
    await waitForAllRowsReady(page);

    const urlAfter = new URL(page.url());
    expect(urlAfter.searchParams.get('start')).toBe(expectedStart);
    const historyAfter = await page.evaluate(() => window.history.length);
    expect(historyAfter).toBe(historyBefore);
    const navCountAfter = await page.evaluate(() => performance.getEntriesByType('navigation').length);
    expect(navCountAfter).toBe(navCountBefore);
  });

  test('keyboard edge-shift in one-day view hydrates immediately with cache-miss skeleton fallback', async ({
    page,
  }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);
    await waitForAllRowsReady(page);

    const oneDayUrl = new URL(page.url());
    oneDayUrl.searchParams.set('days', '1');
    await page.goto(oneDayUrl.toString());

    const container = page.locator('.editor #scroll-container');
    await expect(container).toBeVisible();
    await waitForAllRowsReady(page);

    const startInput = page.locator(START_INPUT_SELECTOR);
    const startBefore = (await startInput.inputValue()).trim();
    const expectedStart = addDays(startBefore, 1);
    const historyBefore = await page.evaluate(() => window.history.length);
    const navCountBefore = await page.evaluate(() => performance.getEntriesByType('navigation').length);

    await page.locator('.editor #scroll-container tbody tr td').first().click();
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(60);

    expect((await statusText(page)).toLowerCase()).not.toContain('scanning');
    await expect.poll(async () => (await startInput.inputValue()).trim(), { timeout: 1000 }).toBe(expectedStart);
    await waitForAllRowsReady(page);

    const urlAfter = new URL(page.url());
    expect(urlAfter.searchParams.get('start')).toBe(expectedStart);
    expect(urlAfter.searchParams.get('days')).toBe('1');
    const historyAfter = await page.evaluate(() => window.history.length);
    expect(historyAfter).toBe(historyBefore);
    const navCountAfter = await page.evaluate(() => performance.getEntriesByType('navigation').length);
    expect(navCountAfter).toBe(navCountBefore);
  });
});
