import { test, expect } from '@playwright/test'

test('runs the frozen rejected-review rework flow', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      'qor-auth',
      JSON.stringify({
        apiKey: 'qor_review_e2e',
        user: { id: 1, username: 'owner', is_admin: false, is_viewer: false }
      })
    )
  })

  const review = {
    id: 17,
    project_id: 7,
    review_type: 'group',
    group_name: 'compute',
    title: 'Compute signoff',
    summary: 'Rework timing evidence',
    status: 'rejected',
    findings: ['WNS remains negative'],
    decisions: [],
    next_steps: ['Upload closure evidence'],
    can_edit: true,
    can_delete: true,
    can_submit: true,
    can_review: false,
    snapshot_provenance: {
      binding: 'frozen',
      id: 8,
      checksum: 'a'.repeat(64),
      week_start: '2026-08-10',
      config_version: 'weekly-v1',
      verified: true
    }
  }
  let updatedPayload
  let submitted = false

  await page.route('**/api/projects', route => route.fulfill({ json: [{ id: 7, name: 'chip' }] }))
  await page.route('**/api/reviews/weekly**', route =>
    route.fulfill({
      json: {
        project_id: 7,
        week_start: '2026-08-10',
        week_end: '2026-08-16',
        timezone: 'Asia/Shanghai',
        input_mode: 'frozen',
        is_frozen: true,
        snapshot: { id: 8, checksum: 'a'.repeat(64) },
        capabilities: {
          can_freeze: false,
          can_create_project_review: false,
          can_view_live_preview: false
        },
        groups: [
          {
            id: 2,
            name: 'compute',
            owner_username: 'owner',
            can_create_review: true,
            modules: []
          }
        ]
      }
    })
  )
  await page.route('**/api/reviews/group?*', route => route.fulfill({ json: { items: [review] } }))
  await page.route('**/api/reviews/group/17?*', async route => {
    if (route.request().method() === 'PUT') {
      updatedPayload = route.request().postDataJSON()
      await route.fulfill({ json: { ...review, ...updatedPayload } })
    } else {
      await route.fulfill({ json: review })
    }
  })
  await page.route('**/api/reviews/group/17/submit', async route => {
    submitted = true
    await route.fulfill({ json: { ...review, status: 'submitted' } })
  })

  await page.goto('/review/group')
  await expect(page.getByText(/已冻结 · Snapshot 8/)).toBeVisible()
  await expect(page.getByRole('button', { name: '冻结本周快照' })).toHaveCount(0)
  await expect(page.getByText('Snapshot 8', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await page.getByLabel(/标题/).fill('Compute signoff reworked')
  await page.getByRole('button', { name: 'Save Review' }).click()
  await expect.poll(() => updatedPayload?.title).toBe('Compute signoff reworked')
  expect(updatedPayload.week_start).toBe('2026-08-10')

  await page.getByRole('button', { name: '重新提交' }).click()
  await expect.poll(() => submitted).toBe(true)

  await page.getByRole('button', { name: '查看详情' }).click()
  const dialog = page.getByRole('dialog', { name: 'Compute signoff' })
  await expect(dialog.getByText('完整性校验通过')).toBeVisible()
})
