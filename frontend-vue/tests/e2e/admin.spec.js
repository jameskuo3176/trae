import { test, expect } from '@playwright/test'

test.describe('Admin Page', () => {
  test('redirects to login when unauthenticated', async ({ page }) => {
    await page.goto('/admin')
    await expect(page).toHaveURL(/\/login/)
  })
})
