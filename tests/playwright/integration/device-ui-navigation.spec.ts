import { expect, test } from '../support/auth-fixture';
import { openSeededDeviceGrid } from '../utils/device-grid';
import { isMockMode, jumpDay } from '../utils/device-ui-interactions';

test.describe('Schedule UI interactions', () => {
  test.skip(!isMockMode, 'Schedule editor interactions require mock fixtures.');
  test.setTimeout(90000);

  test('debounced jump form updates the URL', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const jumpForm = page.locator('nav.jump-form');
    await expect(jumpForm).toBeVisible();

    const startInput = jumpForm.locator('input[name="start"]');
    const startValue = (await startInput.inputValue()).trim();
    const nextStart = jumpDay(startValue, 1);
    const urlBefore = new URL(page.url());

    await startInput.fill(nextStart);
    await expect
      .poll(() => new URL(page.url()).searchParams.get('start'), { timeout: 3000 })
      .toBe(nextStart);
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
});
