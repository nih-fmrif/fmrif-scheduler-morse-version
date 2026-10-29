import type { Page } from '@playwright/test';

import { expect } from '../support/auth-fixture';

export const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';
export const START_INPUT_SELECTOR = 'nav.jump-form input[name="start"]';

const PLACEHOLDER_SELECTOR = ".editor #scroll-container td[data-placeholder='true'] > .slot-placeholder";

function ymd(date: Date) {
  return date.toISOString().slice(0, 10);
}

export function addDays(start: string, deltaDays: number) {
  const value = new Date(`${start}T00:00:00.000Z`);
  return ymd(new Date(value.getTime() + deltaDays * 24 * 60 * 60 * 1000));
}

export async function placeholderCount(page: Page) {
  return page.locator(PLACEHOLDER_SELECTOR).count();
}

export async function statusText(page: Page) {
  return ((await page.locator('#editor-load-status').textContent()) ?? '').trim();
}

export async function visibleHeaderCoverage(page: Page) {
  return page.evaluate(() => {
    const container = document.querySelector('.editor #scroll-container');
    const headerRow = container?.querySelector('thead tr');
    if (!(container instanceof HTMLElement) || !(headerRow instanceof HTMLTableRowElement)) {
      return 0;
    }
    const containerRect = container.getBoundingClientRect();
    const lead = headerRow.children[0];
    const leadWidth =
      lead instanceof HTMLElement
        ? Math.max(0, Math.round(lead.getBoundingClientRect().width))
        : 0;
    const trackStart = containerRect.left + leadWidth;
    const trackEnd = containerRect.right;
    const trackWidth = Math.max(0, trackEnd - trackStart);
    if (trackWidth <= 1) {
      return 0;
    }

    const spans = [...headerRow.querySelectorAll('th')]
      .filter((cell) => !cell.hidden)
      .map((cell) => {
        const rect = cell.getBoundingClientRect();
        const start = Math.max(trackStart, rect.left);
        const end = Math.min(trackEnd, rect.right);
        if (end <= start) {
          return null;
        }
        return [start, end] as [number, number];
      })
      .filter((span): span is [number, number] => Array.isArray(span));
    if (spans.length === 0) {
      return 0;
    }
    spans.sort((a, b) => a[0] - b[0]);
    let covered = 0;
    let cursorStart = spans[0][0];
    let cursorEnd = spans[0][1];
    for (let i = 1; i < spans.length; i += 1) {
      const [start, end] = spans[i];
      if (start <= cursorEnd) {
        cursorEnd = Math.max(cursorEnd, end);
        continue;
      }
      covered += cursorEnd - cursorStart;
      cursorStart = start;
      cursorEnd = end;
    }
    covered += cursorEnd - cursorStart;
    return covered / trackWidth;
  });
}

export async function timeslotLabelWidth(page: Page) {
  return page.evaluate(() => {
    const label = document.querySelector('.editor #scroll-container tbody th');
    if (!(label instanceof HTMLElement)) {
      return 0;
    }
    return label.getBoundingClientRect().width;
  });
}

export async function visibleDayColumnWidth(page: Page) {
  return page.evaluate(() => {
    const cell = [...document.querySelectorAll('.editor #scroll-container thead th')].find(
      (header): header is HTMLElement => header instanceof HTMLElement && !header.hidden
    );
    if (!(cell instanceof HTMLElement)) {
      return 0;
    }
    return cell.getBoundingClientRect().width;
  });
}

export async function waitForAllRowsReady(page: Page) {
  await expect
    .poll(async () => (await statusText(page)).toLowerCase(), { timeout: 15000 })
    .toContain('all 24 rows ready');
  await expect
    .poll(async () => await placeholderCount(page), { timeout: 8000 })
    .toBe(0);
}
