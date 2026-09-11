import { describe, expect, it } from 'vitest'
import { formatRunLabel, joinLabelParts } from '@/composables/useChartPresentation'

const fullRecord = {
  id: 42,
  project_name: 'alpha',
  module_name: 'core',
  version: 'v3.1',
  tag: 'signoff',
  full_dir: '/proj/alpha/core/signoff/run42'
}

describe('joinLabelParts', () => {
  it('joins non-empty parts with newline and omits blanks', () => {
    expect(joinLabelParts(['project', '', 'tag', null, 'directory'])).toBe(
      'project\ntag\ndirectory'
    )
  })
})

describe('formatRunLabel', () => {
  it('stacks project, module, tag, and directory on separate lines for module_tag_dir', () => {
    expect(formatRunLabel(fullRecord, 'module_tag_dir')).toBe(
      'core\nsignoff\n/proj/alpha/core/signoff/run42'
    )
  })

  it('stacks version and tag without duplicate lines when values match', () => {
    expect(formatRunLabel(fullRecord, 'version_tag')).toBe('v3.1\nsignoff')
    expect(formatRunLabel({ id: 1, version: 'v1', tag: 'v1' }, 'version_tag')).toBe('v1')
  })

  it('omits missing fields without blank lines in both mode', () => {
    const record = { id: 7, module_name: 'gpu', version: 'run-a' }
    expect(formatRunLabel(record, 'both', { projectCount: 2, moduleCount: 2 })).toBe('gpu\nrun-a')
  })

  it('shows all four dimensions when project and module are not uniquely selected', () => {
    expect(formatRunLabel(fullRecord, 'both', { projectCount: 2, moduleCount: 2 })).toBe(
      'alpha\ncore\nsignoff'
    )
  })

  it('returns single-field labels unchanged', () => {
    expect(formatRunLabel(fullRecord, 'module')).toBe('core')
    expect(formatRunLabel(fullRecord, 'tag')).toBe('signoff')
    expect(formatRunLabel(fullRecord, 'version')).toBe('v3.1')
  })

  it('falls back when version_tag has no version or tag', () => {
    expect(formatRunLabel({ id: 9 }, 'version_tag')).toBe('#9')
  })
})
