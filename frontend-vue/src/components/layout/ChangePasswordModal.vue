<script setup>
import { ref, watch, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'

const props = defineProps({
  mustChange: { type: Boolean, default: false }
})

const auth = useAuthStore()
const showModal = ref(false)
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const error = ref('')
const success = ref('')
const loading = ref(false)

onMounted(() => {
  if (props.mustChange) {
    showModal.value = true
  }
})

watch(() => props.mustChange, (val) => {
  if (val) {
    showModal.value = true
  }
})

async function handleSubmit() {
  error.value = ''
  success.value = ''
  if (!oldPassword.value || !newPassword.value) {
    error.value = '请填写所有字段'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = '两次输入的新密码不一致'
    return
  }
  loading.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    success.value = '密码修改成功'
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    setTimeout(() => { showModal.value = false }, 1500)
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '修改失败'
  } finally {
    loading.value = false
  }
}

defineExpose({ showModal })
</script>

<template>
  <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
    <div class="modal-content">
      <div class="modal-header">
        <h3>修改密码</h3>
        <button class="close-btn" @click="showModal = false">×</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label>旧密码</label>
          <input v-model="oldPassword" type="password" placeholder="输入旧密码" />
        </div>
        <div class="form-group">
          <label>新密码</label>
          <input v-model="newPassword" type="password" placeholder="输入新密码" />
        </div>
        <div class="form-group">
          <label>确认新密码</label>
          <input v-model="confirmPassword" type="password" placeholder="再次输入新密码" />
        </div>
        <p v-if="error" class="error-text">{{ error }}</p>
        <p v-if="success" class="success-text">{{ success }}</p>
      </div>
      <div class="modal-footer">
        <button class="btn btn-default" @click="showModal = false">取消</button>
        <button class="btn" :disabled="loading" @click="handleSubmit">
          {{ loading ? '提交中...' : '确认修改' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-content {
  background: var(--color-surface);
  border-radius: 12px;
  width: 400px;
  max-width: 90vw;
  border: 1px solid var(--color-border);
}
.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.close-btn {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 20px;
  cursor: pointer;
}
.modal-body {
  padding: 20px;
}
.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.error-text {
  color: #ff5252;
  font-size: 14px;
}
.success-text {
  color: #66bb6a;
  font-size: 14px;
}
</style>