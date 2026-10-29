import { expect, test } from '../support/auth-fixture';
import { openSeededDeviceGrid } from '../utils/device-grid';
import { isMockMode } from '../utils/device-ui-interactions';

test.describe('Schedule UI interactions', () => {
  test.skip(!isMockMode, 'Schedule editor interactions require mock fixtures.');
  test.setTimeout(90000);

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
