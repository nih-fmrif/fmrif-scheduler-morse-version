import { PlaywrightTestConfig } from '@playwright/test';

const config: PlaywrightTestConfig = {
  testDir: './tests',
  timeout: 30000,
  expect: {
    timeout: 5000
  },
  use: {
    baseURL: 'http://localhost:5051',
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
  // Remove webServer config since we're managing Docker separately
  // webServer: {
  //   command: 'docker compose up',
  //   url: 'http://localhost:5051/auth/login',
  //   reuseExistingServer: true,
  //   timeout: 120 * 1000,
  // },
};

export default config;
