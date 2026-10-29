import type { Locator, Page } from '@playwright/test';

import { expect, test } from '../support/auth-fixture';

type Box = { x: number; y: number; width: number; height: number };

async function boundingBox(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) {
    throw new Error('Expected locator to have a bounding box.');
  }
  return box as Box;
}

function expectBelow(upper: Box, lower: Box) {
  expect(lower.y).toBeGreaterThanOrEqual(upper.y + upper.height - 1);
}

async function expectApplyHelperLayout(
  page: Page,
  viewport: { width: number; height: number },
  expectSingleColumn = false
) {
  await page.setViewportSize(viewport);
  await page.goto('/device/d/templates');

  const repairNote = page.locator('.apply-helper-repair-note');
  const instructions = page.locator('.apply-helper-instructions');
  const optionList = page.locator('.template-option-list');
  const firstOption = page.locator('.template-option').first();
  const secondOption = page.locator('.template-option').nth(1);

  await expect(repairNote).toBeVisible();
  await expect(instructions).toBeVisible();
  await expect(optionList).toBeVisible();
  await expect(firstOption).toBeVisible();
  await expect(secondOption).toBeVisible();

  const repairBox = await boundingBox(repairNote);
  const instructionsBox = await boundingBox(instructions);
  const optionListBox = await boundingBox(optionList);

  expectBelow(repairBox, instructionsBox);
  expectBelow(instructionsBox, optionListBox);

  if (expectSingleColumn) {
    const firstOptionBox = await boundingBox(firstOption);
    const secondOptionBox = await boundingBox(secondOption);
    expect(Math.abs(secondOptionBox.x - firstOptionBox.x)).toBeLessThan(2);
    expectBelow(firstOptionBox, secondOptionBox);
  }
}

async function openReviewPending(page: Page) {
  const reviewPendingButton = page.locator('#review-pending');
  await expect(reviewPendingButton).toBeVisible();
  await reviewPendingButton.click();
}

async function gotoTemplateEdit(page: Page, templateId = 'i') {
  await page.goto(`/device/d/templates/edit/${templateId}`);
  await expect(page.locator('.editor-inspector')).toBeVisible();
  await expect(page.locator('#review-pending')).toContainText(/review pending/i);
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

  await page.waitForSelector('entry-cell[data-error="true"]');
  expect(await page.locator('entry-cell[data-error="true"]').count()).toBeGreaterThan(0);
  await expect(page.locator('#review-pending')).toContainText('Review pending');
  await expect(page.locator('#review-pending')).toHaveAttribute('data-invalid-count', /[1-9]/);

  await openReviewPending(page);
  const reviewDialog = page.getByRole('dialog', { name: 'review issues' });
  await expect(reviewDialog).toBeVisible();
  await expect(reviewDialog).toContainText('Active issues');
  await expect(reviewDialog).toContainText(/invalid (group|member|institute)/i);
});

test('rooted invalid cell selection updates the shared inspector card and details modal', async ({
  page,
}) => {
  await gotoTemplateEdit(page);

  const banner = page.locator('.editor-inspector');
  await expect(banner.locator('.editor-inspector-target')).toHaveText('Sun, Mid.');

  await clickFirstInvalidCell(page);

  await expect(banner.locator('.editor-inspector-target')).not.toHaveText('Sun, Mid.');

  await page.getByRole('button', { name: 'Details' }).click();
  const detailsDialog = page.getByRole('dialog', { name: 'Selection Details' });
  await expect(detailsDialog).toBeVisible();
  await expect(detailsDialog.locator('.editor-inspector-detail-summary')).not.toHaveText(
    'open | unassigned | institute: none'
  );
  await expect(detailsDialog.locator('.editor-inspector-detail-errors')).not.toHaveText(
    '0 errors'
  );
  await page.getByRole('button', { name: 'Exit' }).click();

  await clickFirstInvalidCell(page);
  await page.locator('entry-cell[data-error="true"]').first().dblclick();
  await expect(detailsDialog).toBeVisible();
  await page.getByRole('button', { name: 'Exit' }).click();

  await page.locator('.editor #scroll-container').focus();
  await page.keyboard.press('Enter');
  await expect(detailsDialog).toBeVisible();
});

test('template review pending submits clean selected changes and reopens rooted issues for repair', async ({
  page,
}) => {
  await gotoTemplateEdit(page);
  await clickFirstInvalidCell(page);
  await repairActiveCellToNmrf(page);

  await page.getByRole('button', { name: 'Details' }).click();
  const detailsDialog = page.getByRole('dialog', { name: 'Selection Details' });
  await expect(detailsDialog.locator('.editor-inspector-detail-summary')).toHaveText(
    'NMRF | unassigned | institute: NMRF'
  );
  await expect(detailsDialog.locator('.editor-inspector-detail-pending')).toHaveText('1 change');
  await expect(detailsDialog.locator('.editor-inspector-detail-errors')).toHaveText('0 errors');
  await page.getByRole('button', { name: 'Exit' }).click();
  await expect(page.locator('#review-pending')).toContainText('Review pending');
  await expect(page.locator('#review-pending')).toHaveAttribute('data-invalid-count', /[1-9]/);

  await openReviewPending(page);

  const dialog = page.getByRole('dialog', { name: 'review pending changes' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('Active issues');
  await expect(dialog).toContainText('Pending changes');
  await expect(dialog.locator('.review-item-checkbox')).toHaveCount(1);
  await expect(dialog.getByRole('button', { name: 'Publish changes' })).toBeEnabled();
  await dialog.getByRole('button', { name: 'Publish changes' }).click();

  const resultDialog = page.getByRole('dialog', { name: 'results' });
  await expect(resultDialog).toContainText(/1 entry updated/i);
  await expect(resultDialog).toContainText(/stale member/i);
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await expect(page.locator('#review-pending')).toContainText('Review pending');
  await expect(page.locator('#review-pending')).toHaveAttribute('data-invalid-count', /[1-9]/);

  await openReviewPending(page);
  const reviewDialog = page.getByRole('dialog', { name: 'review issues' });
  await expect(reviewDialog).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Refresh review' })
  ).toBeVisible();
  await page.locator('#save-dialog-container .review-item-issue .review-item-action').first().click();
  const reopenedDetailsDialog = page.getByRole('dialog', { name: 'Selection Details' });
  await expect(reopenedDetailsDialog).toBeVisible();
  await expect(reviewDialog).toBeVisible();

  const layering = await page.evaluate(() => {
    const inspectorContainer = document.getElementById('inspector-dialog-container');
    const reviewContainer = document.getElementById('save-dialog-container');
    const inspectorDialog = inspectorContainer?.querySelector('.dialog-box-container');
    if (
      !(inspectorContainer instanceof HTMLElement) ||
      !(reviewContainer instanceof HTMLElement) ||
      !(inspectorDialog instanceof HTMLElement)
    ) {
      throw new Error('Expected review and inspector dialog containers.');
    }

    const rect = inspectorDialog.getBoundingClientRect();
    const topElement = document.elementFromPoint(
      rect.left + rect.width / 2,
      rect.top + rect.height / 2
    );

    return {
      inspectorZIndex: Number.parseInt(getComputedStyle(inspectorContainer).zIndex || '0', 10),
      reviewZIndex: Number.parseInt(getComputedStyle(reviewContainer).zIndex || '0', 10),
      inspectorOnTop: Boolean(topElement?.closest('#inspector-dialog-container')),
    };
  });

  expect(layering.inspectorZIndex).toBeGreaterThan(layering.reviewZIndex);
  expect(layering.inspectorOnTop).toBe(true);

  await repairActiveCellToNmrf(page);
  await page.getByRole('button', { name: 'Exit' }).click();
  await expect(reopenedDetailsDialog).not.toBeVisible();

  const refreshedReviewDialog = page.getByRole('dialog', {
    name: 'review pending changes',
  });
  await expect(refreshedReviewDialog).toBeVisible();
  await expect(refreshedReviewDialog).toContainText('Active issues');
  await expect(refreshedReviewDialog).toContainText('Pending changes');
  await expect(refreshedReviewDialog.locator('.review-item-checkbox')).toHaveCount(1);
  await expect(
    refreshedReviewDialog.getByRole('button', { name: 'Publish changes' })
  ).toBeEnabled();
});

test('template apply helper stacks helper copy and controls without overlap', async ({ page }) => {
  await expectApplyHelperLayout(page, { width: 1280, height: 900 });
  await expectApplyHelperLayout(page, { width: 390, height: 844 }, true);
});

test('manual apply entry blocks repair-required templates before confirm', async ({ page }) => {
  await page.goto('/device/d/templates');

  const field = page.getByRole('textbox', { name: 'templates' });
  const applyButton = page.getByRole('button', { name: 'apply', exact: true });

  expect(await field.evaluate((input) => input.validationMessage)).toBe('');
  await expect(applyButton).toBeDisabled();

  await field.fill('i');
  await expect
    .poll(async () => field.evaluate((input) => input.validationMessage))
    .toContain('repair required template codes cannot be applied: i:');
  await expect(applyButton).toBeDisabled();
  await field.press('Enter');

  await expect(page.getByRole('dialog', { name: 'Apply templates' })).toHaveCount(0);
  const validationMessage = await field.evaluate((input) => input.validationMessage);
  expect(validationMessage).toContain('repair required template codes cannot be applied: i:');
  expect(validationMessage).toMatch(/stale member assignments|stale members in i:/i);
  expect(validationMessage).toMatch(/unavailable groups in i:|invalid groups/i);
});

test('cloned rooted template preserves repair state through archive flow', async ({
  page,
}, testInfo) => {
  const templateId = await pickTemplateCode(page, testInfo.project.name);
  await createClonedTemplate(page, templateId);
  await expect(page.locator('#review-pending')).toHaveAttribute('data-invalid-count', /[1-9]/);
  await expect(page.locator('entry-cell[data-error="true"]')).not.toHaveCount(0);

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
  await expect(page.locator('#review-pending')).toContainText('Review pending');
  await expect(page.locator('#review-pending')).not.toBeDisabled();
  await openReviewPending(page);

  const publishDialog = page.getByRole('dialog', { name: 'review pending changes' });
  await expect(publishDialog).toBeVisible();
  await page.getByRole('button', { name: 'Publish changes' }).click();
  await expect(page.getByRole('dialog', { name: 'results' })).toContainText('entries updated');
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await expect(page.locator('#review-pending')).toContainText('Review pending');
  await expect(page.locator('#review-pending')).toBeDisabled();

  await page.goto('/device/d/templates/list');
  const templateLink = page.getByRole('link', { name: `Clone of i ${templateId} (${templateId})` });
  await expect(templateLink).toBeVisible();
  const templateRow = page.locator('li').filter({ has: templateLink });
  await expect(templateRow.getByText('ready')).toBeVisible();

  await page.goto('/device/d/templates');
  const field = page.getByRole('textbox', { name: 'templates' });
  const applyButton = page.getByRole('button', { name: 'apply', exact: true });
  const readyTemplateButton = page.locator(
    `button[data-tc="${templateId}"][data-template-state="ready"]`
  );

  expect(await field.evaluate((input) => input.validationMessage)).toBe('');
  await expect(applyButton).toBeDisabled();
  await expect(readyTemplateButton).toHaveCount(1);
  await expect(readyTemplateButton).toBeEnabled();
  await readyTemplateButton.click();
  await expect(applyButton).toBeEnabled();
  expect(await field.evaluate((input) => input.validationMessage)).toBe('');

  await applyButton.click();
  await page.getByRole('button', { name: 'apply templates' }).click();

  await expect(page).toHaveURL(/\/device\/d\?start=/);
  await expect(page.getByText('templates applied')).toBeVisible();
});
