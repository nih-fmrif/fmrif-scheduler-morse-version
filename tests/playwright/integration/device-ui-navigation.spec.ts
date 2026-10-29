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
});
