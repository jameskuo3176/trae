import { defineConfig, devices } from '@playwright/test'

const projects = [
  {
    name: 'chromium',
    use: { ...devices['Desktop Chrome'] }
  }
]

if (process.env.PLAYWRIGHT_EXTENDED === '1') {
  projects.push(
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] }
    },
    {
      name: 'msedge',
      use: { ...devices['Desktop Edge'], channel: 'msedge' }
    }
  )
}

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure'
  },
  projects,
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI
  }
})
