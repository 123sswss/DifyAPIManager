export async function api(path, { method = 'GET', body, csrf } = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 12000)
  try {
    const response = await fetch(path, {
      method,
      credentials: 'same-origin',
      signal: controller.signal,
      headers: {
        'X-Requested-With': 'DifyManager',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      const fallback = response.status >= 500 ? '管理服务不可用，请确认后端已启动' : '请求失败，请稍后重试'
      throw Object.assign(new Error(data.message || fallback), { status: response.status })
    }
    return data
  } catch (error) {
    if (error.status) throw error
    throw new Error('无法连接管理服务，请确认服务已启动')
  } finally {
    clearTimeout(timeout)
  }
}
