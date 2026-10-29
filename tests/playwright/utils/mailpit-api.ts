import type { APIRequestContext } from '@playwright/test';

export type MailpitMessageSummary = {
  ID: string;
  Subject: string;
  To?: Array<{ Address?: string; Name?: string }>;
  From?: { Address?: string; Name?: string };
  Snippet?: string;
};

export type MailpitMessageDetail = {
  ID: string;
  Subject: string;
  Text?: string;
  To?: Array<{ Address?: string; Name?: string }>;
  From?: { Address?: string; Name?: string };
};

type MailpitMessagesPayload = {
  messages?: MailpitMessageSummary[];
};

function parsePort(raw: string | undefined): string | null {
  const value = (raw ?? '').trim();
  if (!value) {
    return null;
  }
  if (!/^\d+$/.test(value)) {
    return null;
  }
  const port = Number.parseInt(value, 10);
  if (!Number.isFinite(port) || port < 1 || port > 65535) {
    return null;
  }
  return String(port);
}

export function resolveMailpitApiBaseURL(): string | null {
  const explicit =
    process.env.PLAYWRIGHT_MAILPIT_API_BASE_URL?.trim() ||
    process.env.MAILPIT_API_BASE_URL?.trim() ||
    '';
  if (explicit) {
    return explicit.replace(/\/$/, '');
  }

  const port = parsePort(process.env.MAILPIT__PORT);
  if (!port) {
    return null;
  }
  return `http://127.0.0.1:${port}`;
}

async function requestJson<T>(
  api: APIRequestContext,
  url: string,
  options: { method?: 'GET' | 'DELETE' } = {}
): Promise<T> {
  const method = options.method ?? 'GET';
  const response = await api.fetch(url, { method });
  if (!response.ok()) {
    const body = await response.text();
    throw new Error(`${method} ${url} failed (${response.status()}): ${body}`);
  }

  if (method === 'DELETE') {
    // Mailpit's delete endpoint returns plain text; callers don't need a payload.
    return {} as T;
  }

  return (await response.json()) as T;
}

export async function mailpitAvailable(
  api: APIRequestContext,
  baseURL: string
): Promise<boolean> {
  try {
    await requestJson<Record<string, unknown>>(api, `${baseURL}/api/v1/info`);
    return true;
  } catch {
    return false;
  }
}

export async function clearMailpitMessages(
  api: APIRequestContext,
  baseURL: string
): Promise<void> {
  await requestJson(api, `${baseURL}/api/v1/messages`, { method: 'DELETE' });
}

export async function listMailpitMessages(
  api: APIRequestContext,
  baseURL: string
): Promise<MailpitMessageSummary[]> {
  const payload = await requestJson<MailpitMessagesPayload>(api, `${baseURL}/api/v1/messages`);
  return Array.isArray(payload.messages) ? payload.messages : [];
}

export async function getMailpitMessage(
  api: APIRequestContext,
  baseURL: string,
  messageId: string
): Promise<MailpitMessageDetail> {
  const encodedId = encodeURIComponent(messageId);
  return await requestJson<MailpitMessageDetail>(api, `${baseURL}/api/v1/message/${encodedId}`);
}

export async function waitForMailpitMessage(
  api: APIRequestContext,
  baseURL: string,
  predicate: (message: MailpitMessageSummary) => boolean,
  options: { timeoutMs?: number; pollMs?: number } = {}
): Promise<MailpitMessageSummary | null> {
  const timeoutMs = Math.max(options.timeoutMs ?? 10000, 100);
  const pollMs = Math.max(options.pollMs ?? 200, 50);
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const messages = await listMailpitMessages(api, baseURL);
    const found = messages.find(predicate);
    if (found) {
      return found;
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }

  return null;
}
