import { describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { useDialogFocus } from '@/composables/useDialogFocus'

describe('useDialogFocus', () => {
  it('traps Tab, handles Escape, and restores the opener focus', async () => {
    const open = ref(false)
    const closed = vi.fn()
    const Host = defineComponent({
      setup() {
        const initial = ref(null)
        const { dialogRef, handleDialogKeydown } = useDialogFocus(open, {
          initialFocus: initial,
          onEscape: closed
        })
        return { dialogRef, handleDialogKeydown, initial }
      },
      template: `
        <button class="opener">open</button>
        <div
          v-if="true"
          ref="dialogRef"
          role="dialog"
          tabindex="-1"
          @keydown="handleDialogKeydown"
        >
          <button ref="initial" class="first">first</button>
          <button class="last">last</button>
        </div>
      `
    })
    const wrapper = mount(Host, { attachTo: document.body })
    const opener = wrapper.get('.opener')
    opener.element.focus()
    open.value = true
    await nextTick()
    await nextTick()

    const first = wrapper.get('.first')
    const last = wrapper.get('.last')
    expect(document.activeElement).toBe(first.element)

    first.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true })
    )
    expect(document.activeElement).toBe(last.element)

    last.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    )
    expect(document.activeElement).toBe(first.element)

    first.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    )
    expect(closed).toHaveBeenCalledTimes(1)

    open.value = false
    await nextTick()
    await nextTick()
    expect(document.activeElement).toBe(opener.element)
    wrapper.unmount()
  })
})
