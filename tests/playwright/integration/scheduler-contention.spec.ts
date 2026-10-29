import type { Browser, BrowserContext, Page, TestInfo } from '@playwright/test';

import { expect, test } from '../support/auth-fixture';
import { mockSessionKeyFor } from '../utils/mock-session-key';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';
const baseURL = process.env.TEST_BASE_URL || 'http://localhost:5051';
const actorCount = Math.max(2, Number.parseInt(process.env.PLAYWRIGHT_HEAVY_CONCURRENCY ?? '4', 10) || 4);

type Assignment = {
  group: string;
  member: string;
};

type SlotSnapshot = {
  id: string;
  date: string;
  hour: number;
  group: string;
  member: string;
};

type SavePayload = {
  saved?: number;
  id_map?: Record<string, number>;
  errors?: Record<string, Array<Record<string, unknown>>>;
};

type Actor = {
  context: BrowserContext;
  page: Page;
};

function appUrl(pathOrUrl: string): string {
  return new URL(pathOrUrl, baseURL).toString();
}

function actorSessionKey(testInfo: TestInfo, index: number): string {
  const base = mockSessionKeyFor(testInfo).slice(0, 4);
  return `${base}${index.toString(36)}`.slice(0, 6);
}

function slotDiff(slot: SlotSnapshot, assignment: Assignment) {
  return {
    id: slot.id,
    date: slot.date,
    hour: slot.hour,
    group: [slot.group, assignment.group],
    member: [slot.member, assignment.member],
  };
}

function slotErrorsFor(payload: SavePayload, slotId: string) {
  return Array.isArray(payload.errors?.[slotId]) ? payload.errors?.[slotId] ?? [] : [];
}

async function establishMockActor(page: Page, testInfo: TestInfo, actorIndex: number): Promise<void> {
  const sharedSecret = process.env.AUTH_TEST__SHARED_SECRET;
  if (!sharedSecret) {
    throw new Error('AUTH_TEST__SHARED_SECRET must be set for mock contention coverage.');
  }

  const response = await page.request.post(appUrl('/auth/test/session'), {
    headers: {
      'X-Test-Auth-Secret': sharedSecret,
      'Content-Type': 'application/json',
    },
    data: {
      profile: 'admin',
      reset_profile_state: true,
      session_key: actorSessionKey(testInfo, actorIndex),
    },
  });

  expect(response.ok()).toBeTruthy();
  await page.goto(appUrl('/'));
  await expect(page.locator('.user-menu summary')).toBeVisible();
}

async function createActors(browser: Browser, testInfo: TestInfo, count: number): Promise<Actor[]> {
  const actors = await Promise.all(
    Array.from({ length: count }, async (_, index) => {
      const context = await browser.newContext();
      const page = await context.newPage();
      await establishMockActor(page, testInfo, index + 1);
      return { context, page };
    })
  );

  return actors;
}

async function closeActors(actors: Actor[]): Promise<void> {
  await Promise.all(actors.map(async ({ context }) => context.close().catch(() => undefined)));
}

async function waitForSchedulerRows(page: Page): Promise<void> {
  const container = page.locator('.editor #scroll-container');
  await expect(container).toBeVisible();
  await expect
    .poll(async () => await page.locator('#row-8 entry-cell').count(), { timeout: 15000 })
    .toBeGreaterThan(0);
}

async function pickSchedulableAssignments(page: Page, limit = 2): Promise<Assignment[]> {
  return page.evaluate((targetLimit) => {
    const groups = document.getElementById('groups');
    if (!(groups instanceof HTMLDataListElement)) {
      return [];
    }

    const out: Array<{ group: string; member: string }> = [];
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
      if (!member) {
        continue;
      }

      out.push({ group, member });
      if (out.length >= targetLimit) {
        break;
      }
    }

    return out;
  }, limit);
}

async function findSchedulableFutureWindow(
  page: Page,
  start: string,
  minAssignments: number
): Promise<{ path: string; assignments: Assignment[] }> {
  await page.goto(appUrl('/'));
  const devicePaths = await page
    .locator('[data-home-section="devices"] a.list-card[href^="/device/"]')
    .evaluateAll((links) =>
      [...new Set(links.map((link) => link.getAttribute('href')).filter((href): href is string => !!href))]
    );

  for (const devicePath of devicePaths) {
    const url = new URL(appUrl(devicePath));
    url.searchParams.set('start', start);
    url.searchParams.set('days', '2');
    await page.goto(url.toString());

    if ((await page.locator('.editor #scroll-container').count()) === 0) {
      continue;
    }

    await waitForSchedulerRows(page);
    const assignments = await pickSchedulableAssignments(page, minAssignments);
    if (assignments.length >= minAssignments) {
      return {
        path: `${url.pathname}${url.search}`,
        assignments,
      };
    }
  }

  throw new Error(`No schedulable future device window was available for start=${start}.`);
}

async function readSlotSnapshot(page: Page, date: string, hour: number): Promise<SlotSnapshot> {
  const entry = page.locator(`#row-${hour} entry-cell[data-date="${date}"]`).first();
  await expect(entry).toBeVisible();

  return entry.evaluate((node) => {
    const groupText = node.querySelector('.entry-summary-primary')?.textContent ?? '';
    const memberText = node.querySelector('.entry-summary-secondary')?.textContent ?? '';
    return {
      id: node.getAttribute('data-id') ?? '',
      date: node.getAttribute('data-date') ?? '',
      hour: Number.parseInt(node.getAttribute('data-hour') ?? '-1', 10),
      group: groupText.trim() === 'open' ? '' : groupText.trim(),
      member: memberText.trim() === 'unassigned' ? '' : memberText.trim(),
    };
  });
}

async function csrfTokenFor(page: Page, path: string): Promise<string> {
  await page.goto(appUrl(path));
  await waitForSchedulerRows(page);
  return page.locator('form.editor.schedule-editor #csrf_token').inputValue();
}

async function postSchedulerDiff(
  page: Page,
  path: string,
  csrfToken: string,
  diffs: Array<Record<string, unknown>>
): Promise<SavePayload> {
  const response = await page.request.post(appUrl(path), {
    headers: {
      'Content-Type': 'application/json',
    },
    data: {
      csrf_token: csrfToken,
      payload: {
        diffs,
        notify: false,
      },
    },
  });

  expect(response.ok()).toBeTruthy();
  return (await response.json()) as SavePayload;
}

test.describe('Scheduler contention @heavy', () => {
  test.skip(!isMockMode, 'Scheduler contention coverage requires mock fixtures.');
  test.setTimeout(120000);

  test('allows only one winner during concurrent synthetic-slot creation', async ({ browser, page }, testInfo) => {
    const start = '2035-03-03';
    const { path, assignments } = await findSchedulableFutureWindow(page, start, 1);
    const targetAssignment = assignments[0];
    const blankSlot = await readSlotSnapshot(page, start, 8);

    expect(blankSlot.id.startsWith('new-')).toBeTruthy();
    expect(blankSlot.group).toBe('');
    expect(blankSlot.member).toBe('');

    const actors = await createActors(browser, testInfo, actorCount - 1);
    try {
      const tokens = await Promise.all([
        csrfTokenFor(page, path),
        ...actors.map(({ page: actorPage }) => csrfTokenFor(actorPage, path)),
      ]);

      const diff = slotDiff(blankSlot, targetAssignment);
      const payloads = await Promise.all([
        postSchedulerDiff(page, path, tokens[0], [diff]),
        ...actors.map(({ page: actorPage }, index) =>
          postSchedulerDiff(actorPage, path, tokens[index + 1], [diff])
        ),
      ]);

      const successes = payloads.filter((payload) => Number(payload.saved ?? 0) === 1);
      const failures = payloads.filter((payload) => slotErrorsFor(payload, blankSlot.id).length > 0);

      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(actorCount - 1);
      expect(successes[0]?.id_map?.[blankSlot.id]).toBeTruthy();

      for (const failure of failures) {
        const rows = slotErrorsFor(failure, blankSlot.id);
        expect(rows.length).toBeGreaterThan(0);
        expect(
          rows.some((row) => row.code === 'slot_conflict' || row.type === 'overwrote')
        ).toBeTruthy();
      }

      await page.goto(appUrl(path));
      await waitForSchedulerRows(page);
      const savedSlot = await readSlotSnapshot(page, start, 8);
      expect(savedSlot.id).not.toBe(blankSlot.id);
      expect(savedSlot.group).toBe(targetAssignment.group);
      expect(savedSlot.member).toBe(targetAssignment.member);
    } finally {
      await closeActors(actors);
    }
  });

  test('returns overwrite conflicts for stale updates submitted after another save lands', async ({ browser, page }, testInfo) => {
    const start = '2035-03-04';
    const { path, assignments } = await findSchedulableFutureWindow(page, start, actorCount + 1);
    const baselineAssignment = assignments[0];
    const contenderAssignments = assignments.slice(1, actorCount + 1);
    const blankSlot = await readSlotSnapshot(page, start, 8);
    const initialToken = await page.locator('form.editor.schedule-editor #csrf_token').inputValue();

    const initialCreate = await postSchedulerDiff(page, path, initialToken, [
      slotDiff(blankSlot, baselineAssignment),
    ]);
    expect(initialCreate.saved).toBe(1);

    await page.goto(appUrl(path));
    await waitForSchedulerRows(page);
    const savedSlot = await readSlotSnapshot(page, start, 8);

    expect(savedSlot.id).not.toBe(blankSlot.id);
    expect(savedSlot.group).toBe(baselineAssignment.group);
    expect(savedSlot.member).toBe(baselineAssignment.member);
    expect(contenderAssignments).toHaveLength(actorCount);

    const actors = await createActors(browser, testInfo, actorCount - 1);
    try {
      const tokens = await Promise.all([
        csrfTokenFor(page, path),
        ...actors.map(({ page: actorPage }) => csrfTokenFor(actorPage, path)),
      ]);
      const contenders = [
        { page, token: tokens[0], assignment: contenderAssignments[0] },
        ...actors.map(({ page: actorPage }, index) => ({
          page: actorPage,
          token: tokens[index + 1],
          assignment: contenderAssignments[index + 1],
        })),
      ];

      const winningResult = {
        assignment: contenders[0].assignment,
        payload: await postSchedulerDiff(contenders[0].page, path, contenders[0].token, [
          slotDiff(savedSlot, contenders[0].assignment),
        ]),
      };

      const staleResults = await Promise.all(
        contenders.slice(1).map(async ({ page: contenderPage, token, assignment }) => ({
          assignment,
          payload: await postSchedulerDiff(contenderPage, path, token, [
            slotDiff(savedSlot, assignment),
          ]),
        }))
      );

      const successes = [winningResult];
      const failures = staleResults.filter(({ payload }) => slotErrorsFor(payload, savedSlot.id).length > 0);

      expect(winningResult.payload.saved).toBe(1);
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(actorCount - 1);

      for (const { payload } of failures) {
        const rows = slotErrorsFor(payload, savedSlot.id);
        expect(rows.length).toBeGreaterThan(0);
        expect(rows.some((row) => row.type === 'overwrote')).toBeTruthy();
      }

      await page.goto(appUrl(path));
      await waitForSchedulerRows(page);
      const finalSlot = await readSlotSnapshot(page, start, 8);
      const winningAssignment = winningResult.assignment;

      expect(finalSlot.id).toBe(savedSlot.id);
      expect(finalSlot.group).toBe(winningAssignment.group);
      expect(finalSlot.member).toBe(winningAssignment.member);
    } finally {
      await closeActors(actors);
    }
  });
});
