import type { Page } from '@playwright/test';

import { expect, test } from '../support/auth-fixture';
import { openSeededDeviceGrid } from './device-grid';

export type SlotAssignment = {
  group: string;
  member: string;
};

export const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';

function ymd(date: Date) {
  return date.toISOString().slice(0, 10);
}

export function jumpDay(start: string, deltaDays: number) {
  const value = new Date(`${start}T00:00:00.000Z`);
  return ymd(new Date(value.getTime() + deltaDays * 24 * 60 * 60 * 1000));
}

function projectFutureStart(projectName: string, start: string) {
  const offsets: Record<string, number> = {
    chromium: 0,
    firefox: 14,
    webkit: 28,
  };
  return jumpDay(start, offsets[projectName] ?? 42);
}

export function scopedFutureStart(start: string) {
  return projectFutureStart(test.info().project.name, start);
}

export async function openFutureBlankDeviceGrid(page: Page, start = '2035-02-01') {
  const scopedStart = scopedFutureStart(start);
  await openSeededDeviceGrid(page);
  const url = new URL(page.url());
  url.searchParams.set('start', scopedStart);
  url.searchParams.set('days', '2');
  await page.goto(url.toString());
  await expect(page.locator('.editor #scroll-container')).toBeVisible();
  await expect
    .poll(async () => await page.locator('#row-8 entry-cell').count(), { timeout: 15000 })
    .toBeGreaterThan(0);
  await expect
    .poll(async () => await page.locator('#row-10 entry-cell').count(), { timeout: 15000 })
    .toBeGreaterThan(0);
}

export async function openFutureBlankSchedulableDeviceGrid(page: Page, start = '2035-02-01') {
  const scopedStart = scopedFutureStart(start);
  await page.goto('/');
  const devicePaths = await page
    .locator('[data-home-section="devices"] a.list-card[href^="/device/"]')
    .evaluateAll((links) =>
      [...new Set(links.map((link) => link.getAttribute('href')).filter((href): href is string => !!href))]
    );

  for (const devicePath of devicePaths) {
    const url = new URL(devicePath, page.url());
    url.searchParams.set('start', scopedStart);
    url.searchParams.set('days', '2');
    await page.goto(url.toString());

    const container = page.locator('.editor #scroll-container');
    if ((await container.count()) === 0) {
      continue;
    }

    await expect(container).toBeVisible();
    await expect.poll(async () => await page.locator('#row-8 entry-cell').count(), { timeout: 15000 }).toBeGreaterThan(0);

    const assignment = await pickSchedulableAssignment(page);
    if (assignment) {
      return { assignment };
    }
  }

  throw new Error('No schedulable future device grid was available in the seeded fixture set.');
}

export async function openFutureDeviceGrid(page: Page, device: string, start = '2035-02-01') {
  const scopedStart = scopedFutureStart(start);
  await page.goto(`/device/${device}?start=${scopedStart}&days=2`);
  await expect(page.locator('.editor #scroll-container')).toBeVisible();
  await expect.poll(async () => await page.locator('#row-8 entry-cell').count(), { timeout: 15000 }).toBeGreaterThan(0);
}

export async function grantDeviceSupportPermission(
  page: Page,
  device: string,
  permission: 'medical' | 'training' | 'tech',
  userId = 'user0049'
) {
  await page.goto(`/rbac?scope=device&entity=${device}`);
  await expect(page.getByRole('status')).toContainText('Relationships loaded.');

  const section = page.locator('article.rbac-matrix').filter({
    has: page.getByRole('heading', { name: 'DEV user permissions' }),
  });
  await expect(section).toBeVisible();

  const targetRow = section.locator('tbody tr').filter({ hasText: userId }).first();
  await expect(targetRow).toBeVisible();

  const checkboxIndex =
    permission === 'tech' ? 2 : permission === 'medical' ? 3 : 4;
  const checkbox = targetRow.locator('input[type="checkbox"]').nth(checkboxIndex);
  if (await checkbox.isChecked()) {
    return;
  }

  await checkbox.check();
  await Promise.all([
    page.waitForEvent('dialog').then((dialog) => dialog.accept()),
    section.getByRole('button', { name: /apply permission updates/i }).click(),
  ]);
  await expect(section.getByRole('button', { name: /apply permission updates/i })).toBeDisabled();
}

export async function pickSchedulableAssignment(page: Page): Promise<SlotAssignment | null> {
  return page.evaluate(() => {
    const groups = document.getElementById('groups');
    if (!(groups instanceof HTMLDataListElement)) {
      return null;
    }
    for (const option of [...groups.options]) {
      const group = option.value.trim();
      if (!group) {
        continue;
      }
      const members = document.getElementById(`members-of-${group}`);
      if (!(members instanceof HTMLDataListElement)) {
        continue;
      }
      const member = [...members.options]
        .map((entry) => entry.value.trim())
        .find((value) => value !== '');
      if (member) {
        return { group, member };
      }
    }
    return null;
  });
}

export async function editSlotThroughInspector(
  page: Page,
  hour: number,
  colIndex: number,
  assignment: SlotAssignment
) {
  const row = page.locator(`#row-${hour}`);
  await row.scrollIntoViewIfNeeded();
  await expect.poll(async () => await row.locator('entry-cell').count(), { timeout: 10000 }).toBeGreaterThan(0);

  const cell = row.locator('td').nth(colIndex);
  await cell.dblclick();

  const dialog = page.locator('#inspector-dialog-container .dialog-box-container');
  await expect(dialog).toBeVisible();

  const slotEditor = page.locator('#inspector-slot-editor');
  await slotEditor.locator('input[id^="grp-"]').first().fill(assignment.group);
  await slotEditor.locator('input[id^="mem-"]').first().fill(assignment.member);
  await page.locator('#inspector-exit').click();
  await expect(dialog).not.toBeVisible();
}

export async function openSlotInspectorEditor(
  page: Page,
  hour: number,
  colIndex: number,
  assignment: SlotAssignment
) {
  const row = page.locator(`#row-${hour}`);
  await row.scrollIntoViewIfNeeded();
  await expect.poll(async () => await row.locator('entry-cell').count(), { timeout: 10000 }).toBeGreaterThan(0);

  const cell = row.locator('td').nth(colIndex);
  await cell.dblclick();

  const dialog = page.locator('#inspector-dialog-container .dialog-box-container');
  await expect(dialog).toBeVisible();

  const slotEditor = page.locator('#inspector-slot-editor');
  await slotEditor.locator('input[id^="grp-"]').first().fill(assignment.group);
  await slotEditor.locator('input[id^="mem-"]').first().fill(assignment.member);

  return { cell, dialog, slotEditor };
}
