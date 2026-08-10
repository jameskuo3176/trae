import { test, expect } from '@playwright/test'

test.describe('Dashboard Page', () => {
  test('redirects to login when unauthenticated', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/login/)
  })
})