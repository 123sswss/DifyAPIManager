<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import CoastScene from './components/CoastScene.vue'
import LoginPanel from './components/LoginPanel.vue'
import RequestTable from './components/RequestTable.vue'
import { api } from './api.js'
import './workspace.css'
const currentUser = ref(null)
const csrf = ref('')
const authLoading = ref(true)
const sessionError = ref('')
const isAdmin = computed(() => currentUser.value?.role === 'superuser')
const tabs = computed(() => isAdmin.value
  ? [{ id: 'overview', label: '总览', mark: '◫' }, { id: 'logs', label: '调用日志', mark: '≡' }, { id: 'accounts', label: '用户', mark: '♙' }, { id: 'settings', label: '设置', mark: '⚙' }]
  : [{ id: 'overview', label: '首页', mark: '◫' }, { id: 'settings', label: '设置', mark: '⚙' }])
const themes = [{ id: 'system', name: '跟随时间', mark: '◷' }, { id: 'day', name: '白天', mark: '☀' }, { id: 'evening', name: '傍晚', mark: '◒' }, { id: 'night', name: '夜晚', mark: '☾' }]
const storageKey = 'dify-manager-appearance'
let saved = {}
try { saved = JSON.parse(localStorage.getItem(storageKey)) || {} } catch { /* Use defaults when storage is unavailable. */ }
const theme = ref(themes.some(item => item.id === saved.theme) ? saved.theme : 'system')
const animated = ref(typeof saved.animated === 'boolean' ? saved.animated : !window.matchMedia('(prefers-reduced-motion: reduce)').matches)
const storageMessage = ref('自动保存')
const activeTab = ref('overview')
const coast = ref(null)
const now = ref(new Date())
const dateFilter = ref('today')
const statusFilter = ref('all')
const notice = ref('')
let clockTimer, noticeTimer
const sceneHour = computed(() => theme.value === 'system' ? now.value.getHours() + now.value.getMinutes() / 60 : ({ day: 12, evening: 18.5, night: 0 })[theme.value])
const isNight = computed(() => sceneHour.value < 6 || sceneHour.value >= 20)
const dateLabel = computed(() => new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(now.value))
const activeLabel = computed(() => tabs.value.find(tab => tab.id === activeTab.value)?.label || '首页')
const logData = ref({ available: false, records: [], total: null, summary: null })
const users = ref([])
const dataLoading = ref(false)
const dataError = ref('')
const loggingOut = ref(false)
let dataVersion = 0
const metrics = computed(() => [
  { name: '今日请求', mark: '↗', unit: '次', value: logData.value.summary?.requests ?? '—' },
  { name: '转发完成率', mark: '✓', unit: '%', value: logData.value.summary?.completion_rate ?? '—' },
  { name: '平均耗时', mark: '◷', unit: 'ms', value: logData.value.summary?.average_ms ?? '—' },
])
function acceptSession(result) {
  csrf.value = result.csrf
  activeTab.value = 'overview'
  currentUser.value = result.user
  sessionError.value = ''
}
function clearSession() {
  currentUser.value = null
  csrf.value = ''
  users.value = []
  logData.value = { available: false, records: [], total: null, summary: null }
  dataVersion++
}
async function restoreSession() {
  try { acceptSession(await api('/api/auth/me')) }
  catch (error) { if (error.status !== 401) sessionError.value = error.message }
  finally { authLoading.value = false }
}
async function logout() {
  loggingOut.value = true
  try { await api('/api/auth/logout', { method: 'POST', body: {}, csrf: csrf.value }); clearSession() }
  catch (error) { if (error.status === 401) clearSession(); else tell(error.message) }
  finally { loggingOut.value = false }
}
async function loadData() {
  const version = ++dataVersion
  if (!isAdmin.value || activeTab.value === 'settings') return
  dataLoading.value = true
  dataError.value = ''
  try {
    const accounts = activeTab.value === 'accounts'
    const result = await api(accounts ? '/api/admin/users' : `/api/admin/logs?days=${activeTab.value === 'overview' ? 'today' : dateFilter.value}&status=${activeTab.value === 'overview' ? 'all' : statusFilter.value}`)
    if (version !== dataVersion) return
    if (accounts) users.value = result.users
    else logData.value = result
  } catch (error) {
    if (version !== dataVersion) return
    if (error.status === 401) { clearSession(); sessionError.value = '登录已过期，请重新登录' }
    else dataError.value = error.message
  } finally { if (version === dataVersion) dataLoading.value = false }
}
watch([activeTab, dateFilter, statusFilter, currentUser], loadData)
function tell(message) { notice.value = message; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => { notice.value = '' }, 4000) }
function syncScene() { coast.value?.setTime(sceneHour.value) }
function resetAppearance() { theme.value = 'system'; animated.value = !window.matchMedia('(prefers-reduced-motion: reduce)').matches; tell('已恢复默认外观') }
watch([theme, animated], () => {
  try { localStorage.setItem(storageKey, JSON.stringify({ theme: theme.value, animated: animated.value })); storageMessage.value = '已保存' }
  catch { storageMessage.value = '浏览器存储不可用，偏好仅在本次打开期间生效' }
})
watch(sceneHour, syncScene)
onMounted(() => { restoreSession(); syncScene(); clockTimer = setInterval(() => { now.value = new Date() }, 30000) })
onUnmounted(() => { clearInterval(clockTimer); clearTimeout(noticeTimer) })
</script>

<template>
  <main class="workspace" :class="{ 'is-night': isNight }">
    <div class="landscape-backdrop" aria-hidden="true"><CoastScene ref="coast" :animated="animated" /></div>
    <section class="workspace-panel" :class="{ 'login-panel': !currentUser }" aria-label="Dify API 管理平台">
      <header class="topbar">
        <a class="brand" href="#overview" @click.prevent="activeTab = 'overview'" aria-label="返回总览"><span class="brand-mark" aria-hidden="true">≈</span><span>Dify <strong>API Manager</strong></span></a>
        <div v-if="currentUser" class="account-controls"><span class="account-name">{{ currentUser.username }}<small>{{ isAdmin ? '超级用户' : '普通用户' }}</small></span><button class="text-button" :disabled="loggingOut" @click="logout">{{ loggingOut ? '退出中…' : '退出' }}</button></div>
        <button v-if="currentUser" class="icon-button" aria-label="打开外观设置" title="外观设置" @click="activeTab = 'settings'">☀</button>
      </header>
      <div v-if="authLoading" class="auth-loading" role="status">正在检查登录状态…</div>
      <template v-else-if="!currentUser"><p v-if="sessionError" class="session-error" role="alert">{{ sessionError }}</p><LoginPanel @authenticated="acceptSession" /></template>
      <template v-else>
      <nav class="navigation" aria-label="主导航"><button v-for="tab in tabs" :key="tab.id" :class="{ active: activeTab === tab.id }" :aria-current="activeTab === tab.id ? 'page' : undefined" @click="activeTab = tab.id"><span aria-hidden="true">{{ tab.mark }}</span>{{ tab.label }}</button></nav>
      <div class="page-content" :key="activeTab">
        <div class="page-heading"><div><h1>{{ activeLabel }}</h1></div><span class="heading-date">{{ dateLabel }}</span></div>
        <template v-if="activeTab === 'overview' && !isAdmin"><section class="member-home"><span class="member-avatar" aria-hidden="true">{{ currentUser.username.slice(0, 1).toUpperCase() }}</span><h2>{{ currentUser.username }}</h2><span class="badge">普通用户</span><button class="text-button" @click="activeTab = 'settings'">外观设置 →</button></section></template>
        <template v-else-if="activeTab === 'overview'">
          <section class="service-card" aria-labelledby="service-title"><div class="service-intro"><span class="service-symbol" aria-hidden="true">▤</span><div><div class="inline-heading"><h2 id="service-title">网关服务</h2><span class="badge"><i class="dot" /> 待连接</span></div></div></div><div class="service-details"><div><span>监听地址</span><strong>—</strong></div><div><span>上游连通性</span><strong>待检查</strong></div><div><span>最近检查</span><strong>—</strong></div></div><div class="connection-note"><span aria-hidden="true">ⓘ</span>网关运行状态待接入</div></section>
          <section class="metrics" aria-label="今日使用概况"><article v-for="metric in metrics" :key="metric.name" class="metric-card"><div class="metric-label">{{ metric.name }}<span aria-hidden="true">{{ metric.mark }}</span></div><div class="metric-value">{{ metric.value }} <small>{{ metric.unit }}</small></div></article></section>
          <section class="records-card"><div class="section-heading"><div><h2>最近调用</h2></div><button class="text-button" @click="activeTab = 'logs'">查看全部 <span aria-hidden="true">→</span></button></div><RequestTable :records="logData.records.slice(0, 5)" :loading="dataLoading" :error="dataError" :available="logData.available" /></section>
        </template>
        <template v-else-if="activeTab === 'logs'">
          <section class="records-card"><div class="log-toolbar"><div class="filters"><label>时间范围<select v-model="dateFilter"><option value="today">今天</option><option value="week">最近 7 天</option><option value="month">最近 30 天</option></select></label><label>请求状态<select v-model="statusFilter"><option value="all">全部状态</option><option value="success">HTTP 2xx</option><option value="client">HTTP 4xx</option><option value="server">HTTP 5xx</option></select></label></div><button class="secondary-button" :disabled="dataLoading" @click="loadData"><span aria-hidden="true">↻</span> {{ dataLoading ? '加载中…' : '刷新' }}</button></div><RequestTable :records="dataError ? [] : logData.records" :loading="dataLoading" :error="dataError" :available="logData.available" /><div class="table-footer"><span>记录数 {{ logData.total ?? '—' }}<template v-if="logData.total > 100">（显示最近 100 条）</template></span></div></section>
        </template>
        <template v-else-if="activeTab === 'accounts'">
          <div class="section-heading"><h2>用户账号</h2><button class="text-button" :disabled="dataLoading" @click="loadData">刷新</button></div>
          <p v-if="dataError" class="form-error" role="alert">{{ dataError }}</p><p v-else-if="dataLoading" role="status">正在加载…</p>
          <div v-else class="table-scroll"><table class="users-table"><thead><tr><th>账号</th><th>角色</th><th>状态</th></tr></thead><tbody><tr v-for="account in users" :key="account.username"><td>{{ account.username }}</td><td>{{ account.role === 'superuser' ? '超级用户' : '普通用户' }}</td><td>{{ !account.enabled ? '已停用' : account.password_ready ? '可登录' : '待设置密码' }}</td></tr></tbody></table></div>
        </template>
        <template v-else>
          <section class="settings-card"><div class="section-heading"><div><h2>场景外观</h2></div><span aria-hidden="true">☀</span></div><fieldset class="theme-options"><legend class="sr-only">选择场景光线</legend><label v-for="item in themes" :key="item.id" class="theme-option" :class="[item.id, { selected: theme === item.id }]"><input v-model="theme" type="radio" name="theme" :value="item.id" /><span class="theme-preview"><span aria-hidden="true">{{ item.mark }}</span><span v-if="theme === item.id" class="selected-check" aria-hidden="true">✓</span></span><strong>{{ item.name }}</strong></label></fieldset><div class="setting-row"><div><h3>场景动画</h3></div><button class="toggle" :class="{ enabled: animated }" role="switch" :aria-checked="animated" aria-label="场景动画" @click="animated = !animated"><span /></button></div><div class="settings-footer"><span role="status">{{ storageMessage }}</span><button class="text-button" @click="resetAppearance">恢复默认</button></div></section><section v-if="isAdmin" class="settings-card service-settings"><span class="service-symbol" aria-hidden="true">▤</span><div><h2>网关配置 <span class="badge">待接入</span></h2></div></section>
        </template>
      </div>
      </template>
    </section>
    <div class="toast" v-if="notice" role="status">{{ notice }}</div>
  </main>
</template>
