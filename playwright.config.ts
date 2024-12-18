// import { defineConfig } from '@playwright/test';

// export default defineConfig({
//   testDir: './tests',
//   timeout: 30 * 1000,
//   expect: {
//     timeout: 5000
//   },
//   fullyParallel: true,
//   forbidOnly: !!process.env.CI,
//   retries: process.env.CI ? 2 : 0,
//   workers: process.env.CI ? 1 : undefined,
//   reporter: 'html',
//   use: {
//     baseURL: 'http://127.0.0.1:5000',
//     trace: 'on-first-retry',
//     video: 'on',
//     screenshot: 'only-on-failure'
//   },
//   projects: [
//     {
//       name: 'chromium',
//       use: { 
//         browserName: 'chromium',
//       },
//     }
//   ],
// });

import { PlaywrightTestConfig } from '@playwright/test';

const config: PlaywrightTestConfig = {
  testDir: './tests',
  timeout: 30000,
  expect: {
    timeout: 5000
  },
  use: {
    baseURL: 'http://127.0.0.1:5000',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
      },
    }
  ]
};

export default config;
