import { test, expect } from '@playwright/test'

test.describe('Login Page', () => {
  test('displays login form', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('.login-title')).toHaveText('QoR Recorder')
    await expect(page.locator('input[type="text"]')).toBeVisible()
    await expect(page.locator('input[type="password"]')).toBeVisible()
    await expect(page.locator('.login-btn')).toBeVisible()
  })

  test('shows error for empty credentials', async ({ page }) => {
    await page.goto('/login')
    await page.locator('.login-btn').click()
    await expect(page.locator('.error-text')).toBeVisible()
  })
})
