import { test, expect } from '@playwright/test'

test.describe('Dashboard Page', () => {
  test('redirects to login when unauthenticated', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/login/)
  })

  test('applies and cancels DC Picker drafts in an authenticated dashboard', async ({ page }) => {
    let savedConfig
    await page.addInitScript(() => {
      localStorage.setItem(
        'qor-auth',
        JSON.stringify({
          apiKey: 'qor_e2e',
          user: { id: 1, username: 'engineer', is_admin: false, is_viewer: true }
        })
      )
    })
    await page.route('**/api/dashboard/list', route =>
      route.fulfill({
        json: [{ id: 3, name: 'Default', is_default: true }]
      })
    )
    await page.route('**/api/dashboard/3', route =>
      route.fulfill({
        json: {
          id: 3,
          name: 'Default',
          is_default: true,
          config: { activeView: 'charts', height: 500 }
        }
      })
    )
    await page.route('**/api/dashboard/save', async route => {
      savedConfig = route.request().postDataJSON()
      await route.fulfill({ json: { success: true, id: 3 } })
    })
    await page.route('**/api/projects', route => route.fulfill({ json: [] }))
    await page.route('**/api/qor_data**', route =>
      route.fulfill({
        json: [
          {
            id: 'run-a',
            project_id: 1,
            module_id: '10',
            module_name: 'cpu',
            version: 'regr_a',
            full_dir: '/work/regr_a/main',
            wns: -1
          },
          {
            id: 'run-b',
            project_id: 1,
            module_id: '10',
            module_name: 'cpu',
            version: 'regr_b',
            full_dir: '/work/regr_b/main',
            wns: -0.5
          }
        ]
      })
    )
    await page.route('**/api/v2/projects/*/records/*/raw', route =>
      route.fulfill({
        json: { ok: true, data: { timing: { WNS: -0.5, TNS: -5, NVP: 2 } } }
      })
    )

    await page.goto('/dashboard')
    await page.getByLabel('Configuration name').fill('E2E dashboard')
    await page.getByRole('button', { name: 'Save current' }).click()
    await expect.poll(() => savedConfig?.name).toBe('E2E dashboard')
    expect(savedConfig.config.activeView).toBe('charts')

    await expect(page.getByRole('button', { name: /#/ })).toBeVisible()
    await page.getByRole('button', { name: /#/ }).click()
    const dialog = page.getByRole('dialog', { name: 'DC Comparison Picker' })
    await dialog.getByLabel('Baseline-aware changes').uncheck()
    await dialog.getByLabel('VS draft-selection mode').check()
    await dialog.getByRole('button', { name: 'TNS' }).click()
    await dialog.getByRole('button', { name: 'Apply' }).click()
    await expect(page.getByText(/VS draft:/)).toBeVisible()

    await page.getByRole('button', { name: /#/ }).click()
    await expect(dialog.getByRole('button', { name: 'TNS' })).toHaveClass(/active/)
    await dialog.getByRole('button', { name: 'WNS' }).click()
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await page.getByRole('button', { name: /#/ }).click()
    await expect(dialog.getByRole('button', { name: 'TNS' })).toHaveClass(/active/)
  })
})
