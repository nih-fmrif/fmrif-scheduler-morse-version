import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

const ENTRY_RANGE_REGEX = /All entries are between (\d{4}-\d{1,2}-\d{1,2}) and (\d{4}-\d{1,2}-\d{1,2})/i;
const GOTO_OPTS = { waitUntil: 'domcontentloaded' as const, timeout: 20000 };
const GOTO_ATTEMPTS = 2;
const GOTO_RETRY_DELAY_MS = 250;

function summarizeError(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error);
  const firstLine = text.split('\n', 1)[0].trim();
  return firstLine.slice(0, 200);
}

async function gotoWithRetry(page: Page, path: string, attempts?: string[]): Promise<boolean> {
  let lastError: unknown = null;

  for (let attempt = 1; attempt <= GOTO_ATTEMPTS; attempt += 1) {
    try {
      await page.goto(path, GOTO_OPTS);
      return true;
    } catch (error) {
      lastError = error;
      if (attempt < GOTO_ATTEMPTS) {
        await page.waitForTimeout(GOTO_RETRY_DELAY_MS);
      }
    }
  }

  if (attempts) {
    attempts.push(`${path} -> navigation-error=${summarizeError(lastError)}`);
  }
  return false;
}

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

export async function gotoSeededSparseDevice(page: Page): Promise<{ path: string; sparseRows: number }> {
  const attempts: string[] = [];
  if (!(await gotoWithRetry(page, '/', attempts))) {
    throw new Error(`Could not open home page for device selection. Attempts: ${attempts.join(' | ')}`);
  }

  const devicePaths = await page
    .locator('[data-home-section="devices"] a.list-card[href^="/device/"]')
    .evaluateAll((links) =>
      [...new Set(links.map((link) => link.getAttribute('href')).filter((href): href is string => !!href))]
    );

  if (devicePaths.length === 0) {
    throw new Error('No seeded device links were available on the home page.');
  }

  let fallbackWithGrid: { path: string; sparseRows: number } | null = null;
  for (const devicePath of devicePaths) {
    const candidates = [devicePath];
    const explored = new Set<string>();

    while (candidates.length > 0) {
      const candidate = candidates.shift();
      if (!candidate || explored.has(candidate)) {
        continue;
      }
      explored.add(candidate);

      if (!(await gotoWithRetry(page, candidate, attempts))) {
        continue;
      }

      const sparseRows = await sparseRowCount(page);
      if (sparseRows !== null) {
        attempts.push(`${candidate} -> sparseRows=${sparseRows}`);
        if (sparseRows > 0) {
          return { path: candidate, sparseRows };
        }
        if (fallbackWithGrid === null) {
          fallbackWithGrid = { path: candidate, sparseRows };
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

  if (fallbackWithGrid) {
    if (!(await gotoWithRetry(page, fallbackWithGrid.path, attempts))) {
      throw new Error(`Found fallback grid path but failed to reopen it. Attempts: ${attempts.join(' | ')}`);
    }
    return fallbackWithGrid;
  }

  throw new Error(
    `Could not find a seeded device/date window with sparse schedule rows. Attempts: ${attempts.join(' | ')}`
  );
}

export async function openSeededDeviceGrid(page: Page): Promise<{ path: string; sparseRows: number }> {
  const selected = await gotoSeededSparseDevice(page);
  expect(selected.path).toMatch(/^\/device\/[^/?#]+(?:\?.*)?$/);
  const selectedUrl = new URL(page.url());
  expect(`${selectedUrl.pathname}${selectedUrl.search}`).toBe(selected.path);

  const expando = page.locator('#expando');
  if (await expando.isVisible().catch(() => false)) {
    await expando.click();
  }

  await expect(page.locator('.editor #scroll-container')).toBeVisible();
  await expect(page.locator('.editor #scroll-container')).toHaveClass(/js-grid/);
  await expect(page.locator('#editor-load-status')).toContainText(/rows ready|loading/i);
  await expect
    .poll(
      async () => await page.locator('.editor #scroll-container tbody tr').count(),
      { timeout: 15000 }
    )
    .toBeGreaterThan(0);

  return selected;
}
