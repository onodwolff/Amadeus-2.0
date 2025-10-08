import { defineConfig, devices } from '@playwright/test';

const port = Number(process.env.E2E_PORT ?? 4300);
const host = process.env.E2E_HOST ?? '127.0.0.1';
const baseUrl = process.env.E2E_BASE_URL ?? `http://${host}:${port}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: baseUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure'
  },
  webServer: {
    command: `npm run start -- --host 0.0.0.0 --port ${port}`,
    url: baseUrl,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    }
  ]
});
