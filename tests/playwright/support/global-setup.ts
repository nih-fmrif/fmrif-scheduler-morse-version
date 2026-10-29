import { request } from '@playwright/test';

const baseURL = process.env.PLAYWRIGHT_BASE_URL || process.env.BASE_URL || 'http://localhost:5051';
const timeoutMs = Number.parseInt(process.env.PLAYWRIGHT_APP_READY_TIMEOUT_MS ?? '60000', 10);
const intervalMs = Number.parseInt(process.env.PLAYWRIGHT_APP_READY_INTERVAL_MS ?? '1000', 10);

function shouldIgnoreHTTPSErrorsByDefault(urlString: string): boolean {
  try {
    const parsed = new URL(urlString);
    const isHttps = parsed.protocol === 'https:';
    const isLocalhost = parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1';
    return isHttps && !isLocalhost;
  } catch {
    return false;
  }
}

function parseBooleanEnv(name: string, fallback: boolean = false): boolean {
  const value = process.env[name];
  if (value === undefined) {
    return fallback;
  }
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
}

const ignoreHTTPSErrors = parseBooleanEnv(
  'PLAYWRIGHT_IGNORE_HTTPS_ERRORS',
  shouldIgnoreHTTPSErrorsByDefault(baseURL)
);
const proxyServer = (
  process.env.ALL_PROXY ||
  process.env.all_proxy ||
  process.env.PLAYWRIGHT_PROXY_SERVER ||
  process.env.HTTPS_PROXY ||
  process.env.https_proxy ||
  process.env.HTTP_PROXY ||
  process.env.http_proxy ||
  ''
)
  .trim();

async function delay(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

function looksLikeAppPage(body: string): boolean {
  const hasAppShell = body.includes('login-info');
  const hasLoginPage = body.includes('FMRIF Scheduler') && body.includes('login-btn');
  return hasAppShell || hasLoginPage;
}

export default async function globalSetup() {
  const start = Date.now();
  let lastStatus: number | null = null;
  let lastError: unknown = null;
  const requestContext = await request.newContext({
    baseURL,
    ignoreHTTPSErrors,
    ...(proxyServer ? { proxy: { server: proxyServer } } : {}),
    extraHTTPHeaders: { Accept: 'text/html' },
  });

  try {
    while (Date.now() - start < timeoutMs) {
      try {
        const loginResponse = await requestContext.get('/auth/login', {
          maxRedirects: 10,
          timeout: intervalMs,
        });
        lastStatus = loginResponse.status();
        const loginBody = await loginResponse.text();
        if (loginResponse.ok() && looksLikeAppPage(loginBody)) {
          return;
        }

        const homeResponse = await requestContext.get('/', {
          maxRedirects: 10,
          timeout: intervalMs,
        });
        lastStatus = homeResponse.status();
        const homeBody = await homeResponse.text();
        if (homeResponse.ok() && looksLikeAppPage(homeBody)) {
          return;
        }
      } catch (error) {
        lastError = error;
      }

      await delay(intervalMs);
    }
  } finally {
    await requestContext.dispose();
  }

  const detail = lastError ? `Last error: ${String(lastError)}` : `Last status: ${lastStatus ?? 'unknown'}`;
  throw new Error(`Timed out waiting for app readiness at ${baseURL}. ${detail}`);
}
