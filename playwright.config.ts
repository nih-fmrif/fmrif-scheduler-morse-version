import { PlaywrightTestConfig } from '@playwright/test';

const baseURL = process.env.BASE_URL || 'http://localhost:5051';

const config: PlaywrightTestConfig = {
  testDir: './tests',
  timeout: 30000,
  expect: {
    timeout: 5000
  },
  globalSetup: './tests/global-setup.ts',
  use: {
    baseURL: baseURL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
      },
    }
  ],
};

export default config;
