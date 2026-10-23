<script setup>
import { ref } from 'vue'
import { api } from '../api.js'
const emit = defineEmits(['authenticated'])
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')
async function login() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await api('/api/auth/login', { method: 'POST', body: { username: username.value.trim(), password: password.value } })
    emit('authenticated', result)
  } catch (failure) { error.value = failure.message }
  finally { busy.value = false; password.value = '' }
}
</script>
<template>
  <form class="login-form" @submit.prevent="login">
    <h1>登录</h1>
    <label for="username">账号<input id="username" v-model="username" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required maxlength="48" :disabled="busy" /></label>
    <label for="password">密码<input id="password" v-model="password" name="password" type="password" autocomplete="current-password" required maxlength="256" :disabled="busy" /></label>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <button class="login-submit" type="submit" :disabled="busy">{{ busy ? '正在登录…' : '登录' }}</button>
  </form>
</template>
