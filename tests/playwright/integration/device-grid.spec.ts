import type { Page } from '@playwright/test';
import { test, expect } from '../support/auth-fixture';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';
const ENTRY_RANGE_REGEX = /All entries are between (\d{4}-\d{1,2}-\d{1,2}) and (\d{4}-\d{1,2}-\d{1,2})/i;

async function sparseRowCount(page: Page): Promise<number | null> {
  const container = page.locator('.editor #scroll-container');
  if ((await container.count()) === 0) {
    return null;
  }

  await expect(container).toBeVisible();
  await expect(container).toHaveClass(/js-grid/);

  return container
    .locator('tbody tr')
    .evaluateAll((rows) => rows.filter((row) => row.querySelectorAll('td').length === 0).length);
}

async function gotoSeededSparseDevice(page: Page): Promise<{ path: string; sparseRows: number }> {
  await page.goto('/devices');
  const devicePaths = await page
    .locator('article.list-with-description a[href^="/device/"]')
    .evaluateAll((links) =>
      [...new Set(links.map((link) => link.getAttribute('href')).filter((href): href is string => !!href))]
    );

  if (devicePaths.length === 0) {
    throw new Error('No seeded device paths were available under /devices.');
  }

  const attempts: string[] = [];
  for (const devicePath of devicePaths) {
    const candidates = [devicePath];
    const explored = new Set<string>();

    while (candidates.length > 0) {
      const candidate = candidates.shift();
      if (!candidate || explored.has(candidate)) {
        continue;
      }
      explored.add(candidate);

      await page.goto(candidate);
      const sparseRows = await sparseRowCount(page);
      if (sparseRows !== null) {
        attempts.push(`${candidate} -> sparseRows=${sparseRows}`);
        if (sparseRows > 0) {
          return { path: candidate, sparseRows };
        }
        continue;
      }

      const noteText = (await page.locator('p.note').first().textContent()) ?? '';
      attempts.push(`${candidate} -> note=${noteText.trim()}`);

      const range = noteText.match(ENTRY_RANGE_REGEX);
      if (range) {
        const start = range[1];
        candidates.push(`${devicePath}?start=${start}&days=7`);
      }
    }
  }

  throw new Error(
    `Could not find a seeded device/date window with sparse schedule rows. Attempts: ${attempts.join(' | ')}`
  );
}

test.describe('Device Grid', () => {
  test.skip(!isMockMode, 'Device grid sparse-row coverage requires mock fixtures.');

  test('should initialize editor grid for sparse schedules without nonce/CSP or row errors', async ({
    page,
  }) => {
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

    const selected = await gotoSeededSparseDevice(page);
    expect(selected.path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);

    const sparseRowCount = await page
      .locator('.editor #scroll-container tbody tr')
      .evaluateAll((rows) => rows.filter((row) => row.querySelectorAll('td').length === 0).length);
    expect(sparseRowCount).toBeGreaterThan(0);

    const cspStyleErrors = consoleErrors.filter((text) =>
      text.includes('Refused to apply a stylesheet')
    );
    expect(cspStyleErrors).toEqual([]);

    const gridRowErrors = pageErrors.filter((text) =>
      text.includes("this.cells[r][0].parentElement")
    );
    expect(gridRowErrors).toEqual([]);
  });
});
