import type { Page } from '@playwright/test';

import { expect, test } from '../support/auth-fixture';

async function gotoTemplateEdit(page: Page, templateId = 'i') {
  await page.goto(`/device/d/templates/edit/${templateId}`);
  await expect(page.getByRole('heading', { name: 'template compatibility' })).toBeVisible();
}

async function clickFirstInvalidCell(page: Page) {
  const cell = page.locator('entry-cell[data-error="true"]').first();
  await expect(cell).toBeVisible();
  await cell.click();
}

async function activeEntryId(page: Page) {
  const id = await page
    .locator('entry-cell[data-active="true"]')
    .evaluate((element) => element.getAttribute('data-id'));
  if (!id) {
    throw new Error('Expected an active template cell.');
  }
  return id;
}

async function repairActiveCellToNmrf(page: Page) {
  const entryId = await activeEntryId(page);
  await page.evaluate((id) => {
    const updates = new Map([
      [`grp-${id}`, 'NMRF'],
      [`mem-${id}`, ''],
      [`ins-${id}`, 'NMRF'],
    ]);

    for (const [elementId, value] of updates) {
      const input = document.getElementById(elementId) as HTMLInputElement | null;
      if (!input) {
        throw new Error(`Missing template editor input ${elementId}`);
      }
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }, entryId);
}

async function hydrateAllTemplateRows(page: Page) {
  const rows = page.locator('tr[data-hour]');
  const count = await rows.count();
  for (let index = 0; index < count; index += 1) {
    await rows.nth(index).scrollIntoViewIfNeeded();
  }
  await expect
    .poll(async () => page.locator('tr[data-hour][data-hydrated="true"]').count())
    .toBe(count);
  await rows.first().scrollIntoViewIfNeeded();
}

async function repairAllErrorCellsToNmrf(page: Page) {
  await hydrateAllTemplateRows(page);
  await expect
    .poll(async () => page.locator('entry-cell[data-error="true"]').count())
    .toBeGreaterThan(0);
  return await page.evaluate(() => {
    const cells = Array.from(document.querySelectorAll('entry-cell[data-error="true"]'));
    const ids = cells
      .map((cell) => cell.getAttribute('data-id'))
      .filter((id): id is string => Boolean(id));
    const updates = [
      ['grp', 'NMRF'],
      ['mem', ''],
      ['ins', 'NMRF'],
    ] as const;

    for (const id of ids) {
      for (const [prefix, value] of updates) {
        const input = document.getElementById(`${prefix}-${id}`);
        if (!(input instanceof HTMLInputElement)) {
          throw new Error(`Missing template editor input ${prefix}-${id}`);
        }
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }

    return ids.length;
  });
}

async function pickTemplateCode(page: Page, projectName: string) {
  const projectPools: Record<string, string[]> = {
    chromium: ['x', 'u', 'v'],
    firefox: ['y', 'w', 'q'],
    webkit: ['z', 'r', 's'],
  };
  const candidates = [...(projectPools[projectName] ?? []), 'x', 'y', 'z', 'u', 'v', 'w', 'q', 'r', 's'];
  const existing = new Set(
    await page.locator('datalist option').evaluateAll((options) =>
      options.map((option) => (option as HTMLOptionElement).value)
    )
  );

  for (const candidate of candidates) {
    if (!existing.has(candidate)) {
      return candidate;
    }
  }

  throw new Error(`No free template code available for project ${projectName}.`);
}

async function createClonedTemplate(page: Page, templateId: string, cloneFrom = 'i') {
  await page.goto('/device/d/templates/add');
  await page.locator('input[name="clone_from"]').fill(cloneFrom);
  await page.locator('input[name="id"]').fill(templateId);
  await page.locator('input[name="label"]').fill(`Clone of ${cloneFrom} ${templateId}`);
  await page.locator('textarea[name="description"]').fill(`Rooted clone regression ${templateId}`);
  await page.getByRole('button', { name: 'create' }).click();

  await expect(page).toHaveURL(new RegExp(`/device/d/templates/edit/${templateId}$`));
}

test('rooted template editor shows seeded compatibility state on load', async ({ page }) => {
  await gotoTemplateEdit(page);

  await expect(
    page.getByText('stale members in i:person0075[OLD], person0076[OLD], person0082[OLD], person0086[OLD].')
  ).toBeVisible();
  await expect(page.getByText('unavailable groups in i: EEG, LCCG, NCR, SIEM.')).toBeVisible();
  await page.waitForSelector('entry-cell[data-error="true"]');
  expect(await page.locator('entry-cell[data-error="true"]').count()).toBeGreaterThan(0);
});

test('rooted invalid cell selection updates the visible inspector', async ({ page }) => {
  await gotoTemplateEdit(page);

  const details = page.getByRole('complementary', { name: 'selected slot details' });
  await expect(details.locator('p').nth(0)).toHaveText('Sun, Mid.');
  await expect(details.locator('p').nth(1)).toHaveText('open | unassigned | institute: none');
  await expect(details.locator('dd').nth(2)).toHaveText('0 errors');

  await clickFirstInvalidCell(page);

  await expect(details.locator('p').nth(0)).not.toHaveText('Sun, Mid.');
  await expect(details.locator('p').nth(1)).not.toHaveText('open | unassigned | institute: none');
  await expect(details.locator('dd').nth(2)).not.toHaveText('0 errors');
});

test('template save stays blocked while rooted errors remain unresolved', async ({ page }) => {
  await gotoTemplateEdit(page);
  await clickFirstInvalidCell(page);
  await repairActiveCellToNmrf(page);

  const details = page.getByRole('complementary', { name: 'selected slot details' });
  await expect(details.locator('p').nth(1)).toHaveText('NMRF | unassigned | institute: NMRF');
  await expect(details.locator('dd').nth(1)).toHaveText('1 change');
  await expect(details.locator('dd').nth(2)).toHaveText('0 errors');

  await page.getByRole('button', { name: 'save' }).click();

  const dialog = page.getByRole('dialog', { name: 'outstanding errors' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('all errors must be resolved before submitting');
});

test('manual apply entry blocks repair-required templates before confirm', async ({ page }) => {
  await page.goto('/device/d/templates');

  const field = page.getByRole('textbox', { name: 'templates' });
  await field.fill('i');
  await page.getByRole('button', { name: 'apply' }).click();

  await expect(page.getByRole('dialog', { name: 'Apply templates' })).toHaveCount(0);
  const validationMessage = await field.evaluate((input) => input.validationMessage);
  expect(validationMessage).toContain(
    'repair required template codes cannot be applied: i: i has 20 stale member assignments that must be repaired before save or apply.'
  );
  expect(validationMessage).toContain('unavailable groups in i: EEG, LCCG, NCR, SIEM.');
});

test('cloned rooted template preserves repair state through archive flow', async ({
  page,
}, testInfo) => {
  const templateId = await pickTemplateCode(page, testInfo.project.name);
  await createClonedTemplate(page, templateId);
  await expect(
    page.getByText(
      `stale members in ${templateId}:person0075[OLD], person0076[OLD], person0082[OLD], person0086[OLD].`
    )
  ).toBeVisible();
  await expect(
    page.getByText(`unavailable groups in ${templateId}: EEG, LCCG, NCR, SIEM.`)
  ).toBeVisible();

  await page.getByRole('link', { name: 'edit metadata' }).click();
  await page.getByRole('checkbox', { name: 'archived' }).check();
  await page.getByRole('button', { name: 'save' }).click();

  await page.goto('/device/d/templates/archive');
  await expect(page.getByRole('link', { name: `Clone of i ${templateId} (${templateId})` })).toBeVisible();
  await expect(
    page.getByText(
      `stale members in ${templateId}:person0075[OLD], person0076[OLD], person0082[OLD], person0086[OLD].`
    )
  ).toBeVisible();
  await expect(
    page.getByText(`unavailable groups in ${templateId}: EEG, LCCG, NCR, SIEM.`)
  ).toBeVisible();
});

test('repaired cloned template becomes ready and can be applied', async ({ page }, testInfo) => {
  await page.goto('/device/d/templates/add');
  const templateId = await pickTemplateCode(page, testInfo.project.name);
  await createClonedTemplate(page, templateId);

  const repairedCount = await repairAllErrorCellsToNmrf(page);
  expect(repairedCount).toBeGreaterThan(0);
  await expect
    .poll(async () => page.locator('entry-cell[data-changed="true"]').count())
    .toBe(repairedCount);
  await expect(page.locator('entry-cell[data-error="true"]')).toHaveCount(0);
  await page.getByRole('button', { name: 'save' }).click();

  const publishDialog = page.getByRole('dialog', { name: 'publish changes' });
  await expect(publishDialog).toBeVisible();
  await page.getByRole('button', { name: 'confirm' }).click();
  await expect(page.getByRole('dialog', { name: 'results' })).toContainText('entries updated');
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await expect(page.getByRole('heading', { name: 'template compatibility' })).toHaveCount(0);

  await page.goto('/device/d/templates/list');
  await expect(page.getByRole('link', { name: `Clone of i ${templateId} (${templateId})` })).toBeVisible();
  await expect(page.getByText('ready')).toBeVisible();

  await page.goto('/device/d/templates');
  await page.getByRole('button', { name: `add ${templateId}: Clone of i ${templateId}` }).click();
  await page.getByRole('button', { name: 'apply' }).click();
  await page.getByRole('button', { name: 'apply templates' }).click();

  await expect(page).toHaveURL(/\/device\/d\?start=/);
  await expect(page.getByText('templates applied')).toBeVisible();
});
