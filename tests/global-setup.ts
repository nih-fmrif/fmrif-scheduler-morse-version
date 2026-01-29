const baseURL = process.env.BASE_URL || 'http://localhost:5051';
const rbacMode = process.env.RBAC__SUPERUSER_MODE;
const expectAppShell = rbacMode === 'true';
const expectLoginPage = rbacMode === 'false';
const timeoutMs = Number.parseInt(process.env.PLAYWRIGHT_APP_READY_TIMEOUT_MS ?? '60000', 10);
const intervalMs = Number.parseInt(process.env.PLAYWRIGHT_APP_READY_INTERVAL_MS ?? '1000', 10);

async function delay(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

export default async function globalSetup() {
  const start = Date.now();
  let lastStatus: number | null = null;
  let lastError: unknown = null;

  while (Date.now() - start < timeoutMs) {
    try {
      const response = await fetch(baseURL, { redirect: 'follow' });
      lastStatus = response.status;
      const body = await response.text();

      const hasAppShell = body.includes('nav class="breadcrumb"') && body.includes('login-info');
      const hasLoginPage = body.includes('Device Scheduler') && body.includes('login-btn');

      if (
        response.ok &&
        ((expectAppShell && hasAppShell) ||
          (expectLoginPage && hasLoginPage) ||
          (!expectAppShell && !expectLoginPage && (hasAppShell || hasLoginPage)))
      ) {
        return;
      }
    } catch (error) {
      lastError = error;
    }

    await delay(intervalMs);
  }

  const expectation = expectAppShell ? 'app shell' : expectLoginPage ? 'login page' : 'app shell or login page';
  const detail = lastError ? `Last error: ${String(lastError)}` : `Last status: ${lastStatus ?? 'unknown'}`;
  throw new Error(`Timed out waiting for ${expectation} at ${baseURL}. ${detail}`);
}
