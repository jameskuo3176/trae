import { nextTick, ref, watch } from 'vue'

const FOCUSABLE_SELECTOR = [
  'button:not(:disabled)',
  '[href]',
  'input:not(:disabled)',
  'select:not(:disabled)',
  'textarea:not(:disabled)',
  '[tabindex]:not([tabindex="-1"])'
].join(',')

export function useDialogFocus(open, { initialFocus, canClose, onEscape } = {}) {
  const dialogRef = ref(null)
  let returnFocus = null

  function focusableElements() {
    return [...(dialogRef.value?.querySelectorAll(FOCUSABLE_SELECTOR) || [])].filter(
      element =>
        !element.hasAttribute('hidden') &&
        element.getAttribute('aria-hidden') !== 'true' &&
        element.tabIndex >= 0
    )
  }

  function focusInitial() {
    const target = initialFocus?.value || focusableElements()[0] || dialogRef.value
    target?.focus?.()
  }

  function trapFocus(event) {
    const focusable = focusableElements()
    if (!focusable.length) {
      event.preventDefault()
      dialogRef.value?.focus?.()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  function handleDialogKeydown(event) {
    if (event.key === 'Tab') {
      trapFocus(event)
      return
    }
    if (event.key !== 'Escape' || (canClose && !canClose())) return
    event.preventDefault()
    event.stopPropagation()
    onEscape?.()
  }

  watch(
    open,
    async (isOpen, wasOpen) => {
      if (isOpen) {
        returnFocus = document.activeElement
        await nextTick()
        focusInitial()
      } else if (wasOpen) {
        const target = returnFocus
        returnFocus = null
        await nextTick()
        target?.focus?.()
      }
    },
    { flush: 'post' }
  )

  return {
    dialogRef,
    focusInitial,
    handleDialogKeydown,
    trapFocus
  }
}
