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

test.describe('Schedule UI interactions', () => {
  test.skip(!isMockMode, 'Schedule editor interactions require mock fixtures.');
  test.setTimeout(90000);

  test('should auto-apply jump form inputs without submit', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const jumpForm = page.locator('nav.jump-form');
    await expect(jumpForm).toBeVisible();

    const startInput = jumpForm.locator('input[name="start"]');
    const startValue = (await startInput.inputValue()).trim();
    const nextStart = jumpDay(startValue, 1);

    await startInput.fill(nextStart);
    await expect(page).toHaveURL(new RegExp(`start=${nextStart}`), { timeout: 7000 });
  });

  test('should use fallback day jump and scroll-edge expansion paths', async ({ page }) => {
    const { path } = await openSeededDeviceGrid(page);
    expect(path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);
    const singleDayURL = new URL(page.url());
    singleDayURL.searchParams.set('days', '1');
    await page.goto(singleDayURL.toString());
    const singleDayPath = `${singleDayURL.pathname}${singleDayURL.search}`;
    expect(page.url()).toContain(singleDayPath);

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

    const hasAdjacentWindow = availability.left || availability.right;
    test.skip(!hasAdjacentWindow, 'No adjacent schedule windows available from this date.');

    const container = page.locator('.editor #scroll-container');
    await expect(container).toBeVisible();

    const canScroll = await container.evaluate((node) => {
      return node.scrollWidth > node.clientWidth;
    });

    if (canScroll) {
      const initialColumns = await page
        .locator('.editor table thead th')
        .count();
      const direction = availability.right ? 1 : -1;
      await container.evaluate((node, dir) => {
        if (dir === 1) {
          node.scrollLeft = node.scrollWidth - node.clientWidth;
        } else {
          node.scrollLeft = 0;
        }
        node.dispatchEvent(new Event('scroll'));
      }, direction);

      await expect
        .poll(
          async () =>
            page.locator('.editor table thead th').count(),
          { timeout: 12000 }
        )
        .toBeGreaterThan(initialColumns);
    }

    const scrollContainer = page.locator('.editor #scroll-container');
    await expect(scrollContainer).toBeVisible();
    await scrollContainer.focus();

    const jumpFallback = page.waitForResponse((resp) => resp.url().includes('/schedule-next-day') && resp.request().method() === 'GET', {
      timeout: 12000,
    });
    await page.keyboard.press('ArrowRight');
    await jumpFallback;
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

    const inspectorDialog = page.locator('#inspector-dialog-container .dialog-box-container');
    await expect(inspectorDialog).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(inspectorDialog).not.toBeVisible();
  });
});
