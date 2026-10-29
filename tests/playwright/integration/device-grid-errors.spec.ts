import { test, expect } from '../support/auth-fixture';
import { openSeededDeviceGrid } from '../utils/device-grid';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('Device Grid Error Guards', () => {
  test.skip(!isMockMode, 'Device grid editor assertions require mock fixtures.');
  test.setTimeout(90000);

  test('should render grid without CSP stylesheet or grid runtime errors', async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });
    page.on('pageerror', (err) => {
      pageErrors.push(err.message);
    });

    await openSeededDeviceGrid(page);
    await expect(page.locator('style')).toHaveCount(0);

    const cspStyleErrors = consoleErrors.filter((text) => text.includes('Refused to apply a stylesheet'));
    expect(cspStyleErrors).toEqual([]);

    const gridRowErrors = pageErrors.filter((text) => text.includes("this.cells[r][0].parentElement"));
    expect(gridRowErrors).toEqual([]);
  });
});
