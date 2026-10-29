import { expect, test } from '../support/auth-fixture';
import { openSeededDeviceGrid } from '../utils/device-grid';
import {
  START_INPUT_SELECTOR,
  addDays,
  isMockMode,
  statusText,
  waitForAllRowsReady,
} from '../utils/device-schedule-lateral';

test.describe('Schedule lateral navigation contract', () => {
  test.skip(!isMockMode, 'Schedule editor interactions require mock fixtures.');
  test.setTimeout(90000);

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
