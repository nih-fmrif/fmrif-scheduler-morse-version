import { test } from '../support/auth-fixture';
import { openSeededDeviceGrid } from '../utils/device-grid';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

test.describe('Device Grid Loading', () => {
  test.skip(!isMockMode, 'Device grid editor assertions require mock fixtures.');
  test.setTimeout(90000);

  test('should initialize editor grid with progressive row loading', async ({ page }) => {
    await openSeededDeviceGrid(page);
  });
});
