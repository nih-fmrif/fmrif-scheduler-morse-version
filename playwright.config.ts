import { PlaywrightTestConfig } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

function loadEnvFile(filePath: string): void {
  let data = '';
  try {
    data = fs.readFileSync(filePath, 'utf8');
  } catch {
    return;
  }

  for (const rawLine of data.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) {
      continue;
    }
    const sep = line.indexOf('=');
    if (sep <= 0) {
      continue;
    }
    const key = line.slice(0, sep).trim();
    if (!key || process.env[key] !== undefined) {
      continue;
    }
    let value = line.slice(sep + 1).trim();
    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1);
    }
    process.env[key] = value;
  }
}

loadEnvFile(path.resolve(__dirname, '.env'));

const configuredBaseURL = process.env.TEST_BASE_URL || 'http://localhost:5051';
const flaskApp = process.env.FLASK_APP || 'scheduler.app:create_app';

function parseBooleanEnv(name: string, fallback: boolean = false): boolean {
  const value = process.env[name];
  if (value === undefined) {
    return fallback;
  }
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
}

function normalizeProxyServer(proxyServer?: string): string | undefined {
  if (!proxyServer) {
    return undefined;
  }

  const trimmed = proxyServer.trim();
  if (!trimmed) {
    return undefined;
  }

  // Playwright expects "socks5://", while many shell tools use "socks5h://".
  return trimmed.replace(/^socks5h:\/\//i, 'socks5://');
}

function normalizeBaseURL(urlString: string): string {
  try {
    const parsed = new URL(urlString);
    const isLocalhost = parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1';
    if (isLocalhost) {
      // Local Flask dev server does not terminate TLS; keep local base URLs on HTTP.
      if (parsed.protocol === 'https:') {
        parsed.protocol = 'http:';
      }
    }
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return urlString;
  }
}

function syncLocalBaseURLPort(urlString: string): string {
  const appPort = process.env.APP_PORT?.trim();
  if (!appPort) {
    return urlString;
  }

  try {
    const parsed = new URL(urlString);
    const isLocalhost = parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1';
    if (!isLocalhost) {
      return urlString;
    }
    parsed.port = appPort;
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return urlString;
  }
}

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

const baseURL = normalizeBaseURL(syncLocalBaseURLPort(configuredBaseURL));
process.env.TEST_BASE_URL = baseURL;
const proxyServer = normalizeProxyServer(
  process.env.PLAYWRIGHT_PROXY_SERVER ||
  process.env.ALL_PROXY ||
  process.env.all_proxy ||
  process.env.HTTPS_PROXY ||
  process.env.https_proxy ||
  process.env.HTTP_PROXY ||
  process.env.http_proxy
);
const ignoreHTTPSErrors = parseBooleanEnv(
  'PLAYWRIGHT_IGNORE_HTTPS_ERRORS',
  shouldIgnoreHTTPSErrorsByDefault(baseURL)
);

if (proxyServer) {
  process.env.PLAYWRIGHT_PROXY_SERVER = proxyServer;
}

function buildWebServerConfig() {
  try {
    const parsedBaseURL = new URL(baseURL);
    const isLocalTarget = parsedBaseURL.hostname === 'localhost' || parsedBaseURL.hostname === '127.0.0.1';
    if (!isLocalTarget) {
      return undefined;
    }

    const port = parsedBaseURL.port || '5051';
    const host = parsedBaseURL.hostname;
    const readinessUrl = `${parsedBaseURL.protocol}//${host}:${port}/robots.txt`;
    return {
      command: `FLASK_APP=${flaskApp} flask run --host ${host} --port ${port}`,
      // "/" requires auth in this app; use a public route for server readiness.
      url: readinessUrl,
      // Always start an isolated app server per run to avoid cross-run coupling.
      reuseExistingServer: false,
      timeout: 120000,
    };
  } catch {
    return undefined;
  }
}

const config: PlaywrightTestConfig = {
  testDir: './tests/playwright',
  testIgnore: ['**/live-incident/**'],
  timeout: 30000,
  expect: {
    timeout: 5000
  },
  globalSetup: './tests/playwright/support/global-setup.ts',
  use: {
    baseURL: baseURL,
    trace: 'on-first-retry',
    ignoreHTTPSErrors,
    ...(proxyServer ? { proxy: { server: proxyServer } } : {}),
  },
  webServer: buildWebServerConfig(),
  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
      },
    },
    {
      name: 'firefox',
      use: {
        browserName: 'firefox',
      },
    },
    {
      name: 'webkit',
      use: {
        browserName: 'webkit',
      },
    },
  ],
};

export default config;
