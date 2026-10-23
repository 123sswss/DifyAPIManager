import assert from 'node:assert/strict'
import { createServer as createHttpServer } from 'node:http'
import { test } from 'node:test'
import { createServer as createViteServer } from 'vite'
import config from '../vite.config.js'

test('API proxy preserves the browser origin and host for authentication checks', async () => {
  const requests = []
  const backend = createHttpServer((request, response) => {
    requests.push({ path: request.url, headers: request.headers })
    request.resume()
    response.writeHead(request.headers.origin === `http://${request.headers.host}` ? 204 : 403)
    response.end()
  })
  await new Promise(resolve => backend.listen(0, '127.0.0.1', resolve))
  let vite
  try {
    vite = await createViteServer({
      ...config,
      configFile: false,
      logLevel: 'silent',
      optimizeDeps: { noDiscovery: true, include: [] },
      server: {
        ...config.server,
        host: '127.0.0.1', port: 0, hmr: false,
        proxy: {
          '/api': {
            ...config.server.proxy['/api'],
            target: `http://127.0.0.1:${backend.address().port}`,
          },
        },
      },
    })
    await vite.listen()
    const origin = `http://127.0.0.1:${vite.httpServer.address().port}`
    const headers = { Origin: origin, 'Content-Type': 'application/json', 'X-Requested-With': 'DifyManager' }
    const response = await fetch(`${origin}/api/auth/login`, { method: 'POST', headers, body: '{}' })
    assert.equal(response.status, 204)
    assert.equal(requests[0].headers.host, new URL(origin).host)
    assert.equal(requests[0].headers.origin, origin)
    assert.equal(requests[0].headers['x-requested-with'], 'DifyManager')
    assert.equal(requests[0].path, '/api/auth/login')

    const crossOrigin = await fetch(`${origin}/api/auth/login`, {
      method: 'POST', headers: { ...headers, Origin: 'https://elsewhere.example' }, body: '{}',
    })
    assert.equal(crossOrigin.status, 403)
    assert.equal(requests[1].headers.origin, 'https://elsewhere.example')
  } finally {
    await vite?.close()
    backend.closeAllConnections()
    await new Promise(resolve => backend.close(resolve))
  }
})
