import { test, expect } from '../support/auth-fixture';
import { ensureProfileSession } from '../utils/mock-rbac-session';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';
const adminDbOpsEnabled = (process.env.PLAYWRIGHT_ENABLE_ADMIN_DB_OPS ?? '').trim() === '1';
const adminBackupDir =
  process.env.PLAYWRIGHT_ADMIN_BACKUP_DIR?.trim() || '/tmp/fmrif-scheduler-playwright-backups';

test.describe('Admin Panel DB Operations', () => {
  test.skip(!isMockMode, 'Mock RBAC coverage only runs when PLAYWRIGHT_AUTH_MODE=mock');
  test.skip(
    !adminDbOpsEnabled,
    'Set PLAYWRIGHT_ENABLE_ADMIN_DB_OPS=1 to allow real backup and restore-drill execution.'
  );
  test.use({ authProfile: 'admin' });

  test('runs backup and restore drill from the Admin Panel', async ({ page }, testInfo) => {
    test.slow();
    await ensureProfileSession(page, 'admin', 'test-admin', { testInfo });

    await page.goto('/app/issues');
    await expect(page.getByRole('heading', { name: /potential issues/i })).toBeVisible();

    await page.locator('#ops-backup-directory').fill(adminBackupDir);
    await page.locator('#ops-backup-retention-count').fill('3');
    await page.locator('#ops-backup-max-age-hours').fill('72');
    await page.locator('#ops-backup-min-free-gb').fill('1');
    await page.locator('#ops-restore-interval-days').fill('1');
    await page.locator('#ops-backup-enabled').check();
    await page.locator('#ops-restore-enabled').check();
    await page.getByRole('button', { name: /save admin configuration/i }).click();
    await expect(page.locator('.flash-messages')).toContainText(/admin configuration updated/i);

    await page.getByRole('button', { name: /run backup now/i }).click();
    await expect(page.locator('.flash-messages')).toContainText(/backup completed/i, {
      timeout: 60000,
    });
    await expect(page.locator('body')).toContainText(adminBackupDir);

    await page.getByRole('button', { name: /run restore drill now/i }).click();
    await expect(page.locator('.flash-messages')).toContainText(/restore drill completed/i, {
      timeout: 60000,
    });
    await expect(page.locator('body')).toContainText(/restore drill: success/i);
  });
});
