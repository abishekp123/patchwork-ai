import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
    ['json', { outputFile: 'test-results/results.json' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
  webServer: [
    {
      command: `${process.env.PATCHWORK_TEST_PYTHON || '../backend/.venv/bin/python'} -m uvicorn browser_app:create_browser_app --factory --app-dir ../backend/tests --host 127.0.0.1 --port 8001`,
      url: 'http://127.0.0.1:8001/health',
      env: { PATCHWORK_E2E: '1' },
      reuseExistingServer: false,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 45_000 },
    },
    {
      command: 'npm run dev -- --port 5174',
      url: 'http://127.0.0.1:5174',
      env: { PATCHWORK_API_PROXY_TARGET: 'http://127.0.0.1:8001' },
      reuseExistingServer: false,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 5_000 },
    },
  ],
})
