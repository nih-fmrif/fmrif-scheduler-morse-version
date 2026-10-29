import type { APIRequestContext, Page, TestInfo } from '@playwright/test';

import { test, expect } from '../support/auth-fixture';
import {
  getMailpitMessage,
  listMailpitMessages,
  mailpitAvailable,
  resolveMailpitApiBaseURL,
  waitForMailpitMessage,
} from '../utils/mailpit-api';
import { waitForAppShell } from '../utils/test-helpers';

const isMockMode = (process.env.PLAYWRIGHT_AUTH_MODE ?? 'mock').toLowerCase() === 'mock';
const mailpitApiBaseURL = resolveMailpitApiBaseURL();
const mailSuppressed = (process.env.MAIL__SUPPRESS_SEND ?? 'false').trim().toLowerCase() !== 'false';

async function openFutureDeviceGrid(page: Page, device: string, start: string) {
  await page.goto(`/device/${device}?start=${start}&days=1`);
  await expect(page.locator('.editor #scroll-container')).toBeVisible();
  await expect
    .poll(async () => await page.locator('#row-8 entry-cell').count(), { timeout: 15000 })
    .toBeGreaterThan(0);
}

async function openSlotInspectorEditor(
  page: Page,
  hour: number,
  colIndex: number,
  assignment?: { group: string; member: string }
) {
  const row = page.locator(`#row-${hour}`);
  await row.scrollIntoViewIfNeeded();
  await expect.poll(async () => await row.locator('entry-cell').count(), { timeout: 10000 }).toBeGreaterThan(0);

  const cell = row.locator('td').nth(colIndex);
  await cell.dblclick();

  const dialog = page.locator('#inspector-dialog-container .dialog-box-container');
  await expect(dialog).toBeVisible();

  const slotEditor = page.locator('#inspector-slot-editor');
  if (assignment) {
    await slotEditor.locator('input[id^="grp-"]').first().fill(assignment.group);
    await slotEditor.locator('input[id^="mem-"]').first().fill(assignment.member);
  }

  return { dialog, slotEditor };
}

async function csrfTokenFromPage(page: Page): Promise<string> {
  const token = page.locator('#main input[name="csrf_token"]').first();
  await expect(token).toBeAttached();
  return (await token.inputValue()).trim();
}

function uniqueDeviceId(testInfo: TestInfo, prefix: string) {
  const browserCode = testInfo.project.name.trim().toLowerCase().slice(0, 1) || 'x';
  const nonce = Date.now().toString(36).slice(-2);
  return `${prefix}${browserCode}${testInfo.workerIndex % 10}${nonce}`;
}

async function createNotificationDevice(page: Page, testInfo: TestInfo, prefix: string) {
  const deviceId = uniqueDeviceId(testInfo, prefix);
  const addresses = {
    schedule: `scheduler-${deviceId}@example.com`,
    medical: `medical-${deviceId}@example.com`,
  };

  await page.goto('/rbac?scope=device');
  await waitForAppShell(page);

  const csrfToken = await csrfTokenFromPage(page);
  const createResponse = await page.request.post('/json/v1/rbac/mutate', {
    form: {
      csrf_token: csrfToken,
      mode: 'batch',
      scope: 'device',
      entity: '__create__',
      operations: JSON.stringify([
        {
          kind: 'device.create',
          device: deviceId,
          label: `Notify ${deviceId}`,
          description: 'Playwright notification coverage',
          addr: addresses.schedule,
          med_addr: addresses.medical,
          train_addr: '',
          tech_addr: '',
          active: true,
        },
      ]),
    },
  });

  expect(createResponse.ok()).toBeTruthy();
  const createPayload = await createResponse.json();
  expect(createPayload?.ok).toBeTruthy();

  await page.goto(`/rbac?scope=device&entity=${deviceId}`);
  await waitForAppShell(page);

  const linkResponse = await page.request.post('/json/v1/rbac/mutate', {
    form: {
      csrf_token: await csrfTokenFromPage(page),
      mode: 'batch',
      scope: 'device',
      entity: deviceId,
      operations: JSON.stringify([
        {
          kind: 'device.group.set',
          device: deviceId,
          group: 'BEI',
          linked: true,
        },
      ]),
    },
  });

  expect(linkResponse.ok()).toBeTruthy();
  const linkPayload = await linkResponse.json();
  expect(linkPayload?.ok).toBeTruthy();

  return { deviceId, addresses };
}

async function seedFutureScheduledSlot(
  page: Page,
  deviceId: string,
  start: string,
  assignment: { group: string; member: string }
) {
  await openFutureDeviceGrid(page, deviceId, start);
  const csrfToken = await csrfTokenFromPage(page);
  const response = await page.request.post(`/device/${deviceId}?start=${start}&days=1`, {
    headers: { 'Content-Type': 'application/json' },
    data: {
      csrf_token: csrfToken,
      payload: {
        diffs: [
          {
            id: `new-${start}-08`,
            date: start,
            hour: 8,
            group: ['', assignment.group],
            member: ['', assignment.member],
          },
        ],
        notify: false,
      },
    },
  });

  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  expect(payload?.saved).toBe(1);
}

async function waitForMailByRecipient(
  api: APIRequestContext,
  baseURL: string,
  recipient: string
) {
  const expected = recipient.toLowerCase();
  const summary = await waitForMailpitMessage(
    api,
    baseURL,
    (message) =>
      Array.isArray(message.To) &&
      message.To.some((entry) => String(entry?.Address ?? '').toLowerCase() === expected),
    { timeoutMs: 12000, pollMs: 250 }
  );
  expect(summary).not.toBeNull();
  if (!summary) {
    throw new Error(`Mailpit message lookup timed out for ${recipient}.`);
  }
  return await getMailpitMessage(api, baseURL, summary.ID);
}

function messageHasRecipient(
  message: { To?: Array<{ Address?: string | null } | null> },
  recipient: string
) {
  const expected = recipient.toLowerCase();
  return Array.isArray(message.To)
    ? message.To.some((entry) => String(entry?.Address ?? '').toLowerCase() === expected)
    : false;
}

test.describe('Scheduler notifications', () => {
  test.skip(!isMockMode, 'Scheduler notification delivery checks use mock auth.');
  test.skip(!mailpitApiBaseURL, 'Set MAILPIT__PORT or PLAYWRIGHT_MAILPIT_API_BASE_URL.');
  test.skip(mailSuppressed, 'Set MAIL__SUPPRESS_SEND=false for delivery verification.');
  test.setTimeout(90000);

  test('delivers schedule and medical support emails through Mailpit', async ({ page, request }, testInfo) => {
    const apiBaseURL = mailpitApiBaseURL as string;
    if (!(await mailpitAvailable(request, apiBaseURL))) {
      test.skip(true, `Mailpit API is not reachable at ${apiBaseURL}.`);
      return;
    }

    const { deviceId, addresses } = await createNotificationDevice(page, testInfo, 'n');
    await openFutureDeviceGrid(page, deviceId, '2035-03-02');
    const { dialog, slotEditor } = await openSlotInspectorEditor(page, 8, 0, {
      group: 'BEI',
      member: 'user0048',
    });
    await slotEditor.locator('input[id^="med-requested-"]').first().check();

    await expect(page.locator('#review-pending')).toContainText('Review pending (1)');
    await page.locator('#inspector-save').click();
    await expect(dialog).not.toBeVisible();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    await expect(resultDialog).toContainText(/schedule notification sent/i);
    await expect(resultDialog).toContainText(/medical support notification sent/i);
    await expect
      .poll(async () => await page.locator('#review-pending').textContent(), { timeout: 10000 })
      .toContain('Review pending (0)');

    const scheduleDetail = await waitForMailByRecipient(request, apiBaseURL, addresses.schedule);
    const scheduleText = String(scheduleDetail.Text ?? '');
    expect(scheduleText).toContain('Support Requests');
    expect(scheduleText).toContain('medical');
    expect(scheduleText).toContain('new request');

    const medicalDetail = await waitForMailByRecipient(request, apiBaseURL, addresses.medical);
    const medicalText = String(medicalDetail.Text ?? '');
    expect(medicalText).toContain('new request');
    expect(medicalText).not.toContain('Support Requests');
  });

  test('lets support-only scheduler edits opt out of notification delivery', async ({ page, request }, testInfo) => {
    const apiBaseURL = mailpitApiBaseURL as string;
    if (!(await mailpitAvailable(request, apiBaseURL))) {
      test.skip(true, `Mailpit API is not reachable at ${apiBaseURL}.`);
      return;
    }

    const { deviceId, addresses } = await createNotificationDevice(page, testInfo, 't');
    await seedFutureScheduledSlot(page, deviceId, '2035-03-03', {
      group: 'BEI',
      member: 'user0048',
    });

    await openFutureDeviceGrid(page, deviceId, '2035-03-03');
    const { dialog, slotEditor } = await openSlotInspectorEditor(page, 8, 0);
    await slotEditor.locator('input[id^="med-requested-"]').first().check();
    await page.locator('#inspector-exit').click();
    await expect(dialog).not.toBeVisible();

    await expect(page.locator('#review-pending')).toContainText('Review pending (1)');
    await page.locator('#review-pending').click();

    const saveDialog = page.locator('#save-dialog-container .dialog-box-container');
    await expect(saveDialog).toBeVisible();
    const notificationsToggle = page.locator('#send-notifications');
    await expect(notificationsToggle).toBeVisible();
    await notificationsToggle.uncheck();
    await page.locator('#save-dialog-container button[name="confirm"]').click();

    const resultDialog = page.locator('#result-dialog-container .dialog-box-container');
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog).toContainText(/1 entry updated/i);
    await expect(resultDialog).not.toContainText(/notification sent/i);
    await expect
      .poll(async () => await page.locator('#review-pending').textContent(), { timeout: 10000 })
      .toContain('Review pending (0)');
    await page.waitForTimeout(1000);
    const messages = await listMailpitMessages(request, apiBaseURL);
    expect(messages.some((message) => messageHasRecipient(message, addresses.schedule))).toBeFalsy();
    expect(messages.some((message) => messageHasRecipient(message, addresses.medical))).toBeFalsy();
  });
});
