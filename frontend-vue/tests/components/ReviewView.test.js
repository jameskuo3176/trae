import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReviewView from '@/views/ReviewView.vue'
import { projectsApi } from '@/api/projects'
import { reviewApi } from '@/api/review'

vi.mock('@/api/projects', () => ({
  projectsApi: { list: vi.fn() }
}))

vi.mock('@/api/review', () => ({
  reviewApi: {
    weekly: vi.fn(),
    list: vi.fn(),
    detail: vi.fn(),
    selectStar: vi.fn(),
    clearStar: vi.fn(),
    setRisk: vi.fn(),
    clearRisk: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    createSnapshot: vi.fn(),
    submit: vi.fn(),
    decide: vi.fn()
  }
}))

function newprojectOverview(timingSections) {
  const star = {
    id: 101,
    tag: 'regr_demo_20260812',
    version: 'demo',
    timing_sections: timingSections,
    area_total: 245678.42,
    cell_count: 128450,
    utilization: 68.5,
    source_file: '/workspace/regr_demo/top.v',
    full_dir: '/workspace/regr_demo'
  }
  return {
    week_start: '2026-08-10',
    week_end: '2026-08-16',
    timezone: 'Asia/Shanghai',
    input_mode: 'frozen',
    is_frozen: true,
    snapshot: { id: 8, checksum: 'abcdef1234567890' },
    capabilities: {
      can_freeze: false,
      can_create_project_review: true,
      can_view_live_preview: true
    },
    groups: [
      {
        id: 1,
        name: 'newproject',
        owner_username: 'admin',
        can_create_review: true,
        modules: [
          {
            module_id: 11,
            module_name: 'demoA',
            candidates: [star],
            star,
            can_select_star: false,
            risk: { rating: 'high', details: [] },
            upload_time: '2026-08-12T06:05:00Z'
          }
        ]
      }
    ]
  }
}

async function mountReview(overview, reviews = [], path = '/review/group') {
  projectsApi.list.mockResolvedValue([{ id: 7, name: 'newproject' }])
  reviewApi.weekly.mockResolvedValue(overview)
  reviewApi.list.mockResolvedValue(reviews)
  reviewApi.detail.mockImplementation((_type, id) =>
    Promise.resolve(reviews.find(review => review.id === id))
  )

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/review/group',
        component: ReviewView,
        meta: { reviewType: 'group' }
      },
      {
        path: '/review/project',
        component: ReviewView,
        meta: { reviewType: 'project' }
      }
    ]
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(ReviewView, {
    attachTo: document.body,
    global: { plugins: [router] }
  })
  await flushPromises()
  return wrapper
}

describe('ReviewView timing controls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    document.body.innerHTML = ''
  })

  it('rebuilds newproject rows for multiple timing types and the show-all filter', async () => {
    const wrapper = await mountReview(
      newprojectOverview({
        default: {
          tt0p80v_25c: {
            FUNCCLK: { wns: -10.25, tns: -52.75, nvp: 7, period: 1000, lol: 40 }
          }
        },
        final: {
          tt0p80v_25c: {
            FUNCCLK: { wns: -6.75, tns: -28.5, nvp: 4, period: 1000, lol: 36 },
            IOCLK: { wns: 3.4, tns: 0, nvp: 0, period: 1250, lol: 16 }
          }
        }
      })
    )

    const initialTable = wrapper.get('.aggregate-table').text()
    expect(initialTable).toContain('FUNCCLK')
    expect(initialTable).toContain('final')
    expect(initialTable).not.toContain('IOCLK')
    expect(wrapper.findAll('.global-picker-button')).toHaveLength(1)

    await wrapper.get('.global-picker-button').trigger('click')
    const defaultType = wrapper
      .findAll('.display-picker input[type="checkbox"]')
      .find(input => input.attributes('value') === 'default')
    const showAll = wrapper
      .findAll('.display-picker label')
      .find(label => label.text().includes('显示全部 Path Groups'))
      .find('input')

    await defaultType.setValue(true)
    await showAll.setValue(true)
    await wrapper
      .findAll('.display-picker button')
      .find(button => button.text() === 'Apply')
      .trigger('click')

    const rebuiltTable = wrapper.get('.aggregate-table').text()
    expect(rebuiltTable).toContain('default')
    expect(rebuiltTable).toContain('final')
    expect(rebuiltTable).toContain('IOCLK')
    expect(wrapper.findAll('.path-group-cell')).toHaveLength(3)
  })

  it('collapses an absent timing band to one compact status column', async () => {
    const wrapper = await mountReview(newprojectOverview(undefined))

    expect(wrapper.get('.timing-header').attributes('colspan')).toBe('1')
    expect(wrapper.get('.timing-empty-state').text()).toContain('无 Timing / Path Group 数据')
    expect(wrapper.findAll('.header-columns th').some(header => header.text() === 'WNS')).toBe(
      false
    )
  })

  it('scopes Group routes to the active group and Project routes to all groups', async () => {
    const overview = newprojectOverview()
    overview.groups.push({
      id: 2,
      name: 'graphics',
      owner_username: 'graphics-owner',
      can_create_review: false,
      modules: [
        {
          module_id: 22,
          module_name: 'gpu',
          candidates: [],
          star: null,
          can_select_star: false,
          risk: { rating: 'unrated', details: [] }
        }
      ]
    })

    const groupWrapper = await mountReview(overview)
    expect(groupWrapper.text()).toContain('demoA')
    expect(groupWrapper.text()).not.toContain('gpu')
    groupWrapper.unmount()

    const projectWrapper = await mountReview(overview, [], '/review/project')
    expect(projectWrapper.text()).toContain('demoA')
    expect(projectWrapper.text()).toContain('gpu')
  })

  it('uses weekly capability flags for freeze, create, and star controls', async () => {
    const live = newprojectOverview()
    live.input_mode = 'live_preview'
    live.is_frozen = false
    live.snapshot = null
    live.capabilities.can_freeze = true
    live.capabilities.can_create_project_review = false
    live.groups[0].can_create_review = false
    live.groups[0].modules[0].can_select_star = true
    const wrapper = await mountReview(live)

    expect(wrapper.findAll('button').some(button => button.text() === '冻结本周快照')).toBe(true)
    expect(wrapper.findAll('button').some(button => button.text() === '创建评审')).toBe(false)
    expect(wrapper.get('.aggregate-version-select').attributes('disabled')).toBeUndefined()
  })

  it('stars one of all weekly uploaded runs for a module', async () => {
    const live = newprojectOverview()
    const module = live.groups[0].modules[0]
    live.input_mode = 'live_preview'
    live.is_frozen = false
    live.snapshot = null
    module.can_select_star = true
    module.star_explicit = false
    module.candidates.push({
      ...module.star,
      id: 102,
      tag: 'regr_demo_20260813',
      recorded_at: '2026-08-13T08:00:00Z',
      is_released: false
    })
    reviewApi.selectStar.mockResolvedValue({ ok: true })
    const wrapper = await mountReview(live)

    expect(wrapper.get('.aggregate-star').classes()).toContain('implicit')
    expect(wrapper.get('.aggregate-version-select').text()).toContain('★')
    expect(wrapper.get('.aggregate-version-select').text()).toContain('☆')

    await wrapper.get('.aggregate-star-button').trigger('click')
    await flushPromises()
    expect(reviewApi.selectStar).toHaveBeenCalledWith({
      project_id: 7,
      module_id: 11,
      record_id: '101',
      week_start: '2026-08-10'
    })

    reviewApi.selectStar.mockClear()
    await wrapper.get('.aggregate-version-select').setValue('102')
    await flushPromises()

    expect(reviewApi.selectStar).toHaveBeenCalledWith({
      project_id: 7,
      module_id: 11,
      record_id: '102',
      week_start: '2026-08-10'
    })
  })

  it('clears an explicitly selected weekly star when clicked again', async () => {
    const live = newprojectOverview()
    live.input_mode = 'live_preview'
    live.is_frozen = false
    const module = live.groups[0].modules[0]
    module.can_select_star = true
    module.star_explicit = true
    module.star_source = 'explicit_weekly_upload'
    reviewApi.clearStar.mockResolvedValue({ ok: true, cleared: true })
    const wrapper = await mountReview(live)

    await wrapper.get('.aggregate-star-button').trigger('click')
    await flushPromises()

    expect(reviewApi.clearStar).toHaveBeenCalledWith({
      project_id: 7,
      module_id: 11,
      record_id: '101',
      week_start: '2026-08-10'
    })
  })

  it('labels frozen input and disables official star changes', async () => {
    const overview = newprojectOverview()
    overview.is_frozen = true
    overview.can_live_preview = true
    overview.snapshot = { id: 8, checksum: 'abcdef1234567890' }
    const wrapper = await mountReview(overview)

    expect(wrapper.get('.frozen-notice').text()).toContain('Snapshot 8')
    expect(wrapper.get('.aggregate-version-select').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('查看实时预览')
  })

  it('edits and resets the selected version risk judgement', async () => {
    const overview = newprojectOverview()
    overview.groups[0].modules[0].risk = {
      rating: 'medium',
      auto_rating: 'medium',
      manual_rating: null,
      source: 'automatic',
      details: [],
      can_edit: true
    }
    reviewApi.setRisk.mockResolvedValue({
      ...overview.groups[0].modules[0].risk,
      rating: 'high',
      manual_rating: 'high',
      source: 'manual'
    })
    reviewApi.clearRisk.mockResolvedValue(overview.groups[0].modules[0].risk)
    const wrapper = await mountReview(overview)
    const control = wrapper.get('.risk-cell select')

    await control.setValue('high')
    await flushPromises()
    expect(reviewApi.setRisk).toHaveBeenCalledWith('7', 101, 'high')
    expect(wrapper.get('.risk-cell').text()).toContain('high')

    await control.setValue('')
    await flushPromises()
    expect(reviewApi.clearRisk).toHaveBeenCalledWith('7', 101)
  })

  it('opens the review editor and submits multiline review content', async () => {
    reviewApi.create.mockResolvedValue({ id: 9 })
    const wrapper = await mountReview(
      newprojectOverview({
        final: {
          tt0p80v_25c: {
            FUNCCLK: { wns: -6.75, tns: -28.5, nvp: 4, period: 1000, lol: 36 }
          }
        }
      })
    )

    await wrapper
      .findAll('button')
      .find(button => button.text() === '创建评审')
      .trigger('click')
    expect(wrapper.get('.review-editor').text()).toContain('已根据当前可见周数据预填建议')

    const fields = wrapper.findAll('.editor-field')
    await fields
      .find(field => field.text().includes('决策'))
      .find('textarea')
      .setValue('推进 timing closure\n确认 owner')
    await fields
      .find(field => field.text().includes('下一步'))
      .find('textarea')
      .setValue('复核 FUNCCLK\n跟踪 WNS')
    await wrapper.get('.review-editor').trigger('submit')
    await flushPromises()

    expect(reviewApi.create).toHaveBeenCalledWith(
      'group',
      expect.objectContaining({
        decisions: ['推进 timing closure', '确认 owner'],
        next_steps: ['复核 FUNCCLK', '跟踪 WNS'],
        group_name: 'newproject'
      })
    )
  })

  it.each([
    ['group', '/review/group', 'newproject'],
    ['project', '/review/project', 'newproject']
  ])('opens structured %s history details with timeline', async (reviewType, path, scope) => {
    const review = {
      id: 31,
      project_id: 7,
      review_type: reviewType,
      title: 'Permission policy review',
      group_name: reviewType === 'group' ? scope : undefined,
      project_name: reviewType === 'project' ? scope : undefined,
      period: 'weekly',
      status: 'approved',
      summary: 'Signoff summary',
      verdict: 'Ready for next stage',
      findings: ['WNS converged'],
      decisions: [{ title: 'Release', owner: 'admin' }],
      next_steps: [],
      risks: [],
      key_metrics: { WNS: '-0.02ns' },
      leader_name: 'admin',
      reviewed_by: 1,
      reviewer_name: 'reviewer',
      review_comment: 'Evidence accepted',
      created_at: '2026-08-10T01:00:00Z',
      submitted_at: '2026-08-10T02:00:00Z',
      reviewed_at: '2026-08-10T03:00:00Z',
      updated_at: '2026-08-10T03:00:00Z',
      can_review: false,
      can_submit: false
    }
    const wrapper = await mountReview(newprojectOverview(), [review], path)

    await wrapper.get('.review-detail-button').trigger('click')
    await flushPromises()

    expect(reviewApi.detail).toHaveBeenCalledWith(reviewType, 31, 7)
    expect(wrapper.get('.review-detail-dialog').text()).toContain('Signoff summary')
    expect(wrapper.get('.review-detail-dialog').text()).toContain('关键指标')
    expect(wrapper.get('.review-detail-dialog').text()).toContain('WNS converged')
    expect(wrapper.get('.review-timeline').text()).toContain('创建')
    expect(wrapper.get('.review-outcome').text()).toContain('Evidence accepted')
    expect(wrapper.get('.review-detail-dialog').text()).not.toContain('下一步')
  })

  it.each([
    ['admin reviewing own submitted Group Review', true],
    ['non-admin creator reviewing own submitted Group Review', false],
    ['authorized project owner reviewing another creator', true],
    ['unauthorized group owner, editor, or other user', false]
  ])('gates submitted detail actions for %s', async (_scenario, canReview) => {
    const review = {
      id: 31,
      project_id: 7,
      review_type: 'group',
      title: 'Permission policy review',
      group_name: 'newproject',
      status: 'submitted',
      can_review: canReview,
      can_submit: false
    }
    const wrapper = await mountReview(newprojectOverview(), [review])

    expect(wrapper.findAll('.review-actions button').map(button => button.text())).not.toContain(
      '提交'
    )
    await wrapper.get('.review-detail-button').trigger('click')
    await flushPromises()

    const actionLabels = wrapper
      .findAll('.review-detail-dialog footer button')
      .map(button => button.text())
    expect(actionLabels.includes('批准')).toBe(canReview)
    expect(actionLabels.includes('驳回')).toBe(canReview)
    const detailText = wrapper.get('.review-detail-dialog').text()
    expect(detailText.includes('等待有权限的审核人处理')).toBe(!canReview)
  })

  it('submits only backend-authorized drafts with project identity', async () => {
    reviewApi.submit.mockResolvedValue({ status: 'submitted' })
    const wrapper = await mountReview(newprojectOverview(), [
      {
        id: 41,
        project_id: 7,
        review_type: 'group',
        title: 'Draft',
        status: 'draft',
        can_submit: true
      },
      {
        id: 42,
        project_id: 7,
        review_type: 'group',
        title: 'Unauthorized draft',
        status: 'draft',
        can_submit: false
      }
    ])

    expect(wrapper.findAll('.review-actions button').map(button => button.text())).toEqual([
      '提交',
      '查看详情',
      '查看详情'
    ])
    await wrapper
      .findAll('.review-actions button')
      .find(button => button.text() === '提交')
      .trigger('click')
    await flushPromises()

    expect(reviewApi.submit).toHaveBeenCalledWith('group', 41, 7)
  })

  it('edits and deletes only backend-authorized draft or rejected reviews', async () => {
    reviewApi.update.mockResolvedValue({ id: 51 })
    reviewApi.remove.mockResolvedValue({ ok: true })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const review = {
      id: 51,
      project_id: 7,
      review_type: 'group',
      title: 'Rejected review',
      summary: 'Needs rework',
      findings: ['Fix WNS'],
      decisions: [],
      next_steps: ['Upload evidence'],
      status: 'rejected',
      can_edit: true,
      can_delete: true,
      can_submit: true
    }
    const wrapper = await mountReview(newprojectOverview(), [review])

    await wrapper
      .findAll('button')
      .find(button => button.text() === '编辑')
      .trigger('click')
    expect(wrapper.get('.review-editor input').element.value).toBe('Rejected review')
    await wrapper.get('.review-editor input').setValue('Reworked review')
    await wrapper.get('.review-editor').trigger('submit')
    await flushPromises()
    expect(reviewApi.update).toHaveBeenCalledWith(
      'group',
      51,
      7,
      expect.objectContaining({ title: 'Reworked review', week_start: '2026-08-10' })
    )

    await wrapper
      .findAll('button')
      .find(button => button.text() === '删除')
      .trigger('click')
    await flushPromises()
    expect(reviewApi.remove).toHaveBeenCalledWith('group', 51, 7)
  })

  it('shows frozen provenance integrity and legacy labeling', async () => {
    const frozen = {
      id: 61,
      project_id: 7,
      review_type: 'project',
      title: 'Frozen review',
      status: 'approved',
      can_review: false,
      snapshot_provenance: {
        binding: 'frozen',
        id: 8,
        week_start: '2026-08-10',
        config_version: 'weekly-v1',
        checksum: 'a'.repeat(64),
        verified: true
      }
    }
    const wrapper = await mountReview(newprojectOverview(), [frozen], '/review/project')
    expect(wrapper.get('.provenance-chip').text()).toContain('Snapshot 8')
    await wrapper.get('.review-detail-button').trigger('click')
    await flushPromises()
    expect(wrapper.get('.snapshot-provenance').text()).toContain('完整性校验通过')

    wrapper.unmount()
    const legacyWrapper = await mountReview(
      newprojectOverview(),
      [{ ...frozen, id: 62, snapshot_provenance: { binding: 'legacy_live_unbound' } }],
      '/review/project'
    )
    expect(legacyWrapper.get('.provenance-chip').text()).toContain('Legacy / live-unbound')
  })

  it('captures approval comments, refreshes detail and surfaces backend errors', async () => {
    reviewApi.decide.mockRejectedValue({
      response: { data: { error: '不能审核自己创建的 review' } },
      message: 'Request failed with status code 400'
    })
    const wrapper = await mountReview(newprojectOverview(), [
      {
        id: 32,
        project_id: 7,
        review_type: 'group',
        title: 'Rejected transition',
        group_name: 'newproject',
        status: 'submitted',
        can_review: true,
        can_submit: false
      }
    ])

    await wrapper.get('.review-detail-button').trigger('click')
    await flushPromises()
    await wrapper
      .findAll('.review-detail-dialog button')
      .find(button => button.text() === '批准')
      .trigger('click')
    await wrapper.get('.review-decision-form textarea').setValue('审批依据')
    await wrapper.get('.review-decision-form').trigger('submit')
    await flushPromises()

    expect(reviewApi.decide).toHaveBeenCalledWith('group', 32, 7, 'approve', '审批依据')
    expect(wrapper.get('.review-detail-dialog [role="alert"]').text()).toBe(
      '不能审核自己创建的 review'
    )
  })

  it('traps focus, cancels decisions safely, and restores detail trigger focus', async () => {
    const wrapper = await mountReview(newprojectOverview(), [
      {
        id: 33,
        project_id: 7,
        review_type: 'group',
        title: 'Keyboard review',
        status: 'submitted',
        can_review: true
      }
    ])
    const trigger = wrapper.get('.review-detail-button')
    trigger.element.focus()
    await trigger.trigger('click')
    await flushPromises()
    const dialog = wrapper.get('.review-detail-dialog')
    const closeButton = dialog.get('.picker-close')
    const footerClose = dialog.findAll('footer button').at(-1)
    expect(document.activeElement).toBe(closeButton.element)

    closeButton.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true })
    )
    expect(document.activeElement).toBe(footerClose.element)
    footerClose.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    )
    expect(document.activeElement).toBe(closeButton.element)

    await dialog
      .findAll('button')
      .find(button => button.text() === '批准')
      .trigger('click')
    await flushPromises()
    const comment = dialog.get('.review-decision-form textarea')
    expect(document.activeElement).toBe(comment.element)
    comment.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    )
    await flushPromises()
    expect(wrapper.find('.review-decision-form').exists()).toBe(false)
    expect(wrapper.find('.review-detail-dialog').exists()).toBe(true)

    document.activeElement.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    )
    await flushPromises()

    expect(wrapper.find('.review-detail-dialog').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
  })

  it('ignores Escape while an approval decision is submitting', async () => {
    let resolveDecision
    reviewApi.decide.mockReturnValue(
      new Promise(resolve => {
        resolveDecision = resolve
      })
    )
    const review = {
      id: 34,
      project_id: 7,
      review_type: 'group',
      title: 'Submitting decision',
      status: 'submitted',
      can_review: true
    }
    const wrapper = await mountReview(newprojectOverview(), [review])
    await wrapper.get('.review-detail-button').trigger('click')
    await flushPromises()
    const dialog = wrapper.get('.review-detail-dialog')
    await dialog
      .findAll('button')
      .find(button => button.text() === '批准')
      .trigger('click')
    await flushPromises()
    const comment = dialog.get('textarea')
    await dialog.get('.review-decision-form').trigger('submit')
    comment.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    )
    await flushPromises()

    expect(wrapper.find('.review-detail-dialog').exists()).toBe(true)
    expect(wrapper.find('.review-decision-form').exists()).toBe(true)

    resolveDecision({ status: 'approved' })
    await flushPromises()
  })

  it('traps focus and restores the display-picker trigger on Escape', async () => {
    const wrapper = await mountReview(newprojectOverview())
    const trigger = wrapper.get('.global-picker-button')
    trigger.element.focus()
    await trigger.trigger('click')
    await flushPromises()

    const dialog = wrapper.get('.display-picker')
    const closeButton = dialog.get('.picker-close')
    const applyButton = dialog.findAll('button').find(button => button.text() === 'Apply')
    expect(document.activeElement).toBe(closeButton.element)

    closeButton.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true })
    )
    expect(document.activeElement).toBe(applyButton.element)
    applyButton.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    )
    expect(document.activeElement).toBe(closeButton.element)

    closeButton.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    )
    await flushPromises()
    expect(wrapper.find('.display-picker').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
  })

  it('traps focus and restores the editor trigger on Escape', async () => {
    const wrapper = await mountReview(newprojectOverview())
    const trigger = wrapper.findAll('button').find(button => button.text() === '创建评审')
    trigger.element.focus()
    await trigger.trigger('click')
    await flushPromises()

    const dialog = wrapper.get('.review-editor')
    const titleInput = dialog.get('input')
    const closeButton = dialog.get('.picker-close')
    const submitButton = dialog.get('button[type="submit"]')
    expect(document.activeElement).toBe(titleInput.element)

    closeButton.element.focus()
    closeButton.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true })
    )
    expect(document.activeElement).toBe(submitButton.element)
    submitButton.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    )
    expect(document.activeElement).toBe(closeButton.element)

    closeButton.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    )
    await flushPromises()
    expect(wrapper.find('.review-editor').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
  })

  it('renders star source_file paths as client gvim links in detail mode', async () => {
    const overview = newprojectOverview()
    overview.groups[0].modules[0].star.source_file = '/workspace/rtl/demoA.sv'
    overview.groups[0].modules[0].star.full_dir = '/workspace/runs/demoA'
    const wrapper = await mountReview(overview)
    await wrapper.get('.actions-cell .btn').trigger('click')
    await flushPromises()

    const links = wrapper.findAll('.gvim-link').map(node => node.attributes('href'))
    expect(links).toContain('gvim://open?path=%2Fworkspace%2Frtl%2FdemoA.sv')
    expect(links).toContain('gvim://open?path=%2Fworkspace%2Fruns%2FdemoA')
  })
})
