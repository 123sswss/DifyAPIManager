<script setup>
defineProps({ records: { type: Array, default: () => [] }, loading: Boolean, error: String, available: Boolean })
const endpoints = { workflow_run: '工作流运行', workflow_detail: '运行详情', chat_messages: '聊天', knowledge: '知识库', files: '文件', other: '其他' }
const outcomes = { forwarded: '转发完成', forwarding: '处理中', invalid_key: '密钥无效', key_disabled: '密钥停用', key_expired: '密钥过期', quota_exhausted: '额度耗尽', timeout: '超时', connection_interrupted: '连接中断' }
function timestamp(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false }) }
</script>
<template>
  <div class="table-scroll"><table><thead><tr><th>请求时间</th><th>方法</th><th>接口类别</th><th>HTTP 状态</th><th>耗时</th><th>传输结果</th></tr></thead><tbody>
    <tr v-for="record in records" :key="record.id"><td>{{ timestamp(record.started_utc) }}</td><td>{{ record.method }}</td><td>{{ endpoints[record.endpoint] || '其他' }}</td><td>{{ record.http_status ?? '—' }}</td><td>{{ record.elapsed_ms == null ? '—' : `${record.elapsed_ms} ms` }}</td><td>{{ outcomes[record.outcome] || record.outcome }}</td></tr>
    <tr v-if="!records.length"><td colspan="6"><div class="empty-state compact" role="status"><span class="empty-symbol" aria-hidden="true">≡</span><h3>{{ loading ? '正在加载…' : error || (available ? '暂无调用记录' : '暂无网关数据') }}</h3></div></td></tr>
  </tbody></table></div>
</template>
