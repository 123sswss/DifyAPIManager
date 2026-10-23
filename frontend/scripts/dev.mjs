import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const project = fileURLToPath(new URL('../../', import.meta.url))
const children = new Set()
let stopping = false

function stop(code = 0) {
  if (stopping) return
  stopping = true
  process.exitCode = code
  for (const child of children) child.kill()
}

function start(command, args, cwd, name) {
  const child = spawn(command, args, {
    cwd,
    stdio: ['inherit', 'inherit', 'inherit'],
    env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
  })
  children.add(child)
  child.on('error', () => {
    console.error(`${name}启动失败，请检查运行环境。`)
    children.delete(child)
    stop(1)
  })
  child.on('exit', code => {
    children.delete(child)
    if (!stopping) {
      if (name === '管理后端') console.error('管理后端已退出，前端一并停止。')
      stop(name === '管理后端' ? 1 : (code ?? 1))
    }
  })
}

async function backendReady() {
  let response
  try {
    response = await fetch('http://127.0.0.1:8788/api/auth/me', { signal: AbortSignal.timeout(1000) })
  } catch { return false }
  const body = await response.json().catch(() => ({}))
  if (response.status === 401 && body.code === 'login_required') return true
  throw new Error('8788 端口已被其他服务占用，请检查后重试。')
}

process.on('SIGINT', () => stop())
process.on('SIGTERM', () => stop())

try {
  if (await backendReady()) {
    console.log('管理后端已运行，复用 http://127.0.0.1:8788')
  } else {
    console.log('正在启动管理后端…')
    start(process.env.PYTHON || 'python', ['-u', 'manager_server.py'], project, '管理后端')
    let ready = false
    for (let attempt = 0; attempt < 40 && !stopping; attempt++) {
      if (await backendReady()) { ready = true; break }
      await new Promise(resolve => setTimeout(resolve, 250))
    }
    if (!ready) throw new Error('管理后端启动失败，请查看上方错误；需要 Python 3.10 或更新版本。')
  }
  if (!stopping) {
    start(process.execPath, [fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url)),
      '--host', '127.0.0.1', ...process.argv.slice(2)], frontend, '前端')
  }
} catch (error) {
  console.error(error.message)
  stop(1)
}
