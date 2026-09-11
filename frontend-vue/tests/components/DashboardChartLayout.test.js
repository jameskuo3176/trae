import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('Dashboard chart layout', () => {
  it('uses one full-width grid column for every dashboard instrument', () => {
    const dashboardPath = resolve(process.cwd(), 'src/views/DashboardView.vue')
    const source = readFileSync(dashboardPath, 'utf8')
    expect(source).toMatch(/\.charts-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s)
    expect(source).not.toContain('class="span-2"')
    expect(source.match(/<RunNotesPanel\s*\/>/g)).toHaveLength(1)
    expect(source).toMatch(
      /<\/Suspense>\s*<Suspense>\s*<section\s+id="section-notes"\s+class="anchor-target">\s*<RunNotesPanel\s*\/>\s*<\/section>/
    )
  })

  it('widens only the dashboard canvas while retaining mobile side padding', () => {
    const dashboardPath = resolve(process.cwd(), 'src/views/DashboardView.vue')
    const source = readFileSync(dashboardPath, 'utf8')

    expect(source).toMatch(
      /\.dashboard-page\s*\{[^}]*width:\s*min\(1920px,\s*calc\(100vw\s*-\s*32px\)\)/s
    )
    expect(source).toMatch(
      /@media\s*\(max-width:\s*600px\)\s*\{[\s\S]*?\.dashboard-page\s*\{[^}]*width:\s*calc\(100vw\s*-\s*16px\)/
    )
  })
})
