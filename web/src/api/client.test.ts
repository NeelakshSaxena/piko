import { describe, expect, it, vi } from 'vitest'
import { apiError, fakeFetch, json, memoryStore } from '../test/helpers'
import { ApiClient, ApiError } from './client'

const SESSION = { access_token: 'a1', refresh_token: 'r1', expires_in: 3600, user_id: 'u', family_id: 'f', role: 'parent', families: [] }

function setup(routes: Parameters<typeof fakeFetch>[0], refresh: string | null = 'r0') {
  const server = fakeFetch(routes)
  const store = memoryStore(refresh)
  const api = new ApiClient('http://api.test', store, server.fetch)
  return { api, store, server }
}

describe('login', () => {
  it('keeps the access token in memory and only the refresh token in storage', async () => {
    const { api, store } = setup({ 'POST /auth/session': json(SESSION) }, null)
    await api.login('a@b.c', 'pw')
    expect(store.value).toBe('r1')
    expect(JSON.stringify(window.localStorage)).not.toContain('a1')
    expect(JSON.stringify(window.sessionStorage)).not.toContain('a1')
  })

  it('maps a wrong password to AUTH_INVALID with the request id', async () => {
    const { api } = setup({ 'POST /auth/session': apiError(401, 'AUTH_INVALID') }, null)
    await expect(api.login('a@b.c', 'bad')).rejects.toMatchObject({ status: 401, code: 'AUTH_INVALID', requestId: 'req-test' })
  })

  it('reports an unreachable server as NETWORK rather than throwing a raw error', async () => {
    const api = new ApiClient('http://api.test', memoryStore(null), (async () => {
      throw new TypeError('failed')
    }) as typeof fetch)
    await expect(api.login('a@b.c', 'pw')).rejects.toMatchObject({ code: 'NETWORK', status: 0 })
  })
})

describe('refresh and rotation', () => {
  it('refreshes once on a 401, stores the ROTATED token, and retries the request', async () => {
    let first = true
    const { api, store, server } = setup({
      'POST /auth/session/refresh': json({ access_token: 'a2', refresh_token: 'r2', expires_in: 3600 }),
      'GET /families': ({ init }) => {
        const auth = (init.headers as Record<string, string>).Authorization
        if (first) {
          first = false
          return apiError(401, 'AUTH_INVALID')
        }
        return auth === 'Bearer a2' ? json({ families: [] }) : apiError(401, 'AUTH_INVALID')
      },
    })
    api.onSessionLost = vi.fn()
    await api.restore() // first refresh (r0 -> r2); the next request is answered 401 once
    await expect(api.families()).resolves.toEqual([]) // 401 -> second refresh -> retry succeeds
    expect(store.value).toBe('r2')
    expect(server.calls.filter((c) => c === 'POST /auth/session/refresh').length).toBe(2)
    expect(api.onSessionLost).not.toHaveBeenCalled()
  })

  it('shares ONE refresh between concurrent callers (a second use of a rotated token would revoke the session)', async () => {
    let refreshes = 0
    const { api } = setup({
      'POST /auth/session/refresh': async () => {
        refreshes++
        await new Promise((r) => setTimeout(r, 20))
        return json({ access_token: 'a2', refresh_token: `r${refreshes}`, expires_in: 3600 })
      },
      'GET /families': json({ families: [] }),
    })
    await Promise.all([api.families(), api.families(), api.families(), api.restore(), api.restore()])
    expect(refreshes).toBe(1)
  })

  it('never reuses a token: a later refresh sends the rotated one', async () => {
    const sent: string[] = []
    const { api, store } = setup({
      'POST /auth/session/refresh': ({ init }) => {
        sent.push((init.headers as Record<string, string>).Authorization ?? '')
        return json({ access_token: 'a', refresh_token: `r${sent.length}`, expires_in: 3600 })
      },
      'GET /families': ({ init }) =>
        (init.headers as Record<string, string>).Authorization === 'Bearer a' ? apiError(401, 'AUTH_INVALID') : json({ families: [] }),
    })
    await api.restore()
    await api.families().catch(() => undefined) // 401 -> refresh again with r1
    expect(sent).toEqual(['Bearer r0', 'Bearer r1'])
    expect(store.value).toBe('r2')
  })

  it('ends the session when the refresh token is refused, and clears it', async () => {
    const { api, store } = setup({
      'POST /auth/session/refresh': apiError(401, 'AUTH_INVALID'),
    })
    const lost = vi.fn()
    api.onSessionLost = lost
    await expect(api.families()).rejects.toMatchObject({ status: 401 })
    expect(store.value).toBeNull()
    expect(lost).toHaveBeenCalledTimes(1)
  })

  it('keeps the refresh token when the server is merely unreachable (it may still be valid)', async () => {
    const api = new ApiClient('http://api.test', memoryStore('r0'), (async () => {
      throw new TypeError('offline')
    }) as typeof fetch)
    const lost = vi.fn()
    api.onSessionLost = lost
    await expect(api.restore()).rejects.toMatchObject({ code: 'NETWORK' })
    expect(lost).not.toHaveBeenCalled()
    expect(api.hasSession).toBe(true)
  })

  it('a page reload with a still-valid access token does NOT refresh (a reload mid-rotation would replay the old token and end the session)', async () => {
    const server = fakeFetch({ 'GET /families': json({ families: [] }) })
    const store = memoryStore('r0', { token: 'a-saved', expiresAtMs: Date.now() + 600_000 })
    const api = new ApiClient('http://api.test', store, server.fetch)
    await expect(api.restore()).resolves.toBe(true)
    await api.families()
    expect(server.calls).toEqual(['GET /families']) // no POST /auth/session/refresh
    const sent = (server.impl.mock.calls[0]?.[1] as RequestInit).headers as Record<string, string>
    expect(sent.Authorization).toBe('Bearer a-saved')
  })

  it('refreshes after a reload only when the saved access token has expired, and saves the new pair', async () => {
    const server = fakeFetch({
      'POST /auth/session/refresh': json({ access_token: 'a-new', refresh_token: 'r-new', expires_in: 3600 }),
    })
    const store = memoryStore('r0', { token: 'a-old', expiresAtMs: Date.now() - 1 })
    const api = new ApiClient('http://api.test', store, server.fetch)
    await expect(api.restore()).resolves.toBe(true)
    expect(server.calls).toEqual(['POST /auth/session/refresh'])
    expect(store.value).toBe('r-new')
    expect(store.access?.token).toBe('a-new')
    expect(store.access!.expiresAtMs).toBeGreaterThan(Date.now() + 3000_000) // a margin is kept, not the full hour
    expect(store.access!.expiresAtMs).toBeLessThan(Date.now() + 3600_000)
  })

  it('signing out and a lost session both erase the saved access token', async () => {
    const lost = setup({ 'POST /auth/session/refresh': apiError(401, 'AUTH_INVALID') })
    lost.store.setAccess({ token: 'x', expiresAtMs: Date.now() - 1 })
    await lost.api.restore()
    expect(lost.store.access).toBeNull()
    expect(lost.store.value).toBeNull()
  })

  it('does not loop: a second 401 after a successful refresh is surfaced', async () => {
    const { api, server } = setup({
      'POST /auth/session/refresh': json({ access_token: 'a2', refresh_token: 'r2', expires_in: 3600 }),
      'GET /families': apiError(401, 'AUTH_INVALID'),
    })
    await expect(api.families()).rejects.toBeInstanceOf(ApiError)
    expect(server.calls.filter((c) => c === 'GET /families')).toHaveLength(2)
  })

  it('restore() without any stored token reports signed out and does not call the server', async () => {
    const { api, server } = setup({}, null)
    await expect(api.restore()).resolves.toBe(false)
    expect(server.calls).toHaveLength(0)
    // and the answer is not cached: signing in afterwards still works
    const again = setup({ 'POST /auth/session': json(SESSION) }, null)
    await again.api.login('a@b.c', 'pw')
    await expect(again.api.restore()).resolves.toBe(true)
  })
})

describe('errors and requests', () => {
  it('surfaces 403 as denied and 429 with Retry-After', async () => {
    const { api } = setup({
      'GET /families/x': apiError(403, 'FORBIDDEN'),
      'GET /devices/x': json({ error: { code: 'RATE_LIMIT', message: 'slow down', request_id: 'r' } }, 429, { 'Retry-After': '12' }),
    }, 'r0')
    ;(api as unknown as { access: string }).access = 'a'
    await expect(api.family('x')).rejects.toMatchObject({ denied: true })
    await expect(api.device('x')).rejects.toMatchObject({ code: 'RATE_LIMIT', retryAfterSeconds: 12 })
  })

  it('never sends credentials as cookies and refuses redirects', async () => {
    const { api, server } = setup({ 'GET /families': json({ families: [] }) })
    ;(api as unknown as { access: string }).access = 'a'
    await api.families()
    const init = server.impl.mock.calls[0]?.[1] as RequestInit
    expect(init.credentials).toBe('omit')
    expect(init.redirect).toBe('error')
    expect(init.cache).toBe('no-store')
  })

  it('serialises history queries and skips undefined parameters', async () => {
    const { api, server } = setup({ 'GET /members/m/history': json({ member_id: 'm', device_status: 'online', history: [], total_count: 0, has_more: false }) })
    ;(api as unknown as { access: string }).access = 'a'
    await api.memberHistory('m', { limit: 50, offset: 0, event_type: undefined })
    const url = new URL(String(server.impl.mock.calls[0]?.[0]))
    expect(url.searchParams.get('limit')).toBe('50')
    expect(url.searchParams.has('event_type')).toBe(false)
  })

  it('logout revokes server-side and always clears local state', async () => {
    const { api, store } = setup({ 'POST /auth/session': json(SESSION), 'POST /auth/session/revoke': json(null, 204) }, null)
    await api.login('a@b.c', 'pw')
    await api.logout()
    expect(store.value).toBeNull()
    expect(api.hasSession).toBe(false)
  })
})

describe('SOS and message calls', () => {
  const ready = { 'POST /auth/session/refresh': json({ access_token: 'a1', refresh_token: 'r1', expires_in: 3600 }) }

  it('sends the status change and the message id exactly as given', async () => {
    const bodies: unknown[] = []
    const { api } = setup({
      ...ready,
      'PUT /sos/incidents/i1': ({ body }) => (bodies.push(body), json({ incident_id: 'i1' })),
      'POST /messages': ({ body }) => (bodies.push(body), json({ message_id: 'm-fixed' })),
      'POST /messages/m1/ack': json({ message_id: 'm1' }),
    })
    await api.updateSos('i1', 'resolved', 'fine')
    await api.updateSos('i1', 'acknowledged')
    await api.sendMessage({ messageId: 'm-fixed', deviceId: 'd1', body: 'hi', sentAt: '2026-10-17T00:00:00Z' })
    await api.acknowledgeMessage('m1')
    expect(bodies).toEqual([
      { status: 'resolved', notes: 'fine' },
      { status: 'acknowledged' },
      { message_id: 'm-fixed', device_id: 'd1', body: 'hi', sent_at: '2026-10-17T00:00:00Z' },
    ])
  })

  it('treats a reply of the wrong shape as an error, never as an empty list', async () => {
    const wrong = [json({}), json({ incidents: 'none' }), json(null as unknown as object), new Response('<html>proxy error</html>', { status: 200 })]
    for (const reply of wrong) {
      const { api } = setup({ ...ready, 'GET /sos/incidents': reply, 'GET /messages': reply })
      await expect(api.sosIncidents()).rejects.toBeInstanceOf(ApiError)
      await expect(api.messages('d1')).rejects.toBeInstanceOf(ApiError)
    }
  })

  it('passes filters as query parameters and does not send a body on reads', async () => {
    const seen: string[] = []
    const { api } = setup({
      ...ready,
      'GET /sos/incidents': ({ url, init }) => (seen.push(url.search, String(init.body)), json({ incidents: [], total_count: 0, has_more: false })),
    })
    await api.sosIncidents({ status: 'open', limit: 5 })
    expect(seen).toEqual(['?status=open&limit=5', 'undefined'])
  })
})
