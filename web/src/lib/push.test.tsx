import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { PushSetup } from '../components/PushSetup'
import { disablePush, enablePush, pushState, urlBase64ToBytes } from './push'
import swSource from '../../public/sw.js?raw'
import { fakeFetch, json, memoryStore } from '../test/helpers'

const ENDPOINT = 'https://fcm.googleapis.com/fcm/send/abc'
const KEYS = { p256dh: 'B' + 'A'.repeat(86), auth: 'A'.repeat(22) }

interface Browser {
  permission: NotificationPermission
  subscription: { endpoint: string; toJSON: () => unknown; unsubscribe: ReturnType<typeof vi.fn> } | null
  subscribe: ReturnType<typeof vi.fn>
  requestPermission: ReturnType<typeof vi.fn>
}

/** A browser with the Push API, driven by the test. Nothing is sent anywhere. */
function installBrowser(initial: Partial<Browser> = {}): Browser {
  const browser: Browser = {
    permission: 'default',
    subscription: null,
    subscribe: vi.fn(),
    requestPermission: vi.fn(),
    ...initial,
  }
  const makeSub = () => ({
    endpoint: ENDPOINT,
    toJSON: () => ({ endpoint: ENDPOINT, keys: KEYS }),
    unsubscribe: vi.fn(async () => {
      browser.subscription = null
      return true
    }),
  })
  browser.subscribe.mockImplementation(async () => (browser.subscription = makeSub()))
  browser.requestPermission.mockImplementation(async () => {
    browser.permission = 'granted'
    return 'granted'
  })
  const registration = {
    pushManager: { getSubscription: async () => browser.subscription, subscribe: browser.subscribe },
  }
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
  Object.defineProperty(window, 'PushManager', { value: function PushManager() {}, configurable: true })
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: { register: vi.fn(async () => registration), getRegistration: vi.fn(async () => registration), ready: Promise.resolve(registration) },
  })
  const Notif = function Notification() {} as unknown as { permission: NotificationPermission; requestPermission: () => Promise<NotificationPermission> }
  Object.defineProperty(Notif, 'permission', { get: () => browser.permission })
  Notif.requestPermission = browser.requestPermission as () => Promise<NotificationPermission>
  Object.defineProperty(window, 'Notification', { value: Notif, configurable: true })
  return browser
}

function removeBrowser() {
  for (const key of ['PushManager', 'Notification']) delete (window as unknown as Record<string, unknown>)[key]
  delete (navigator as unknown as Record<string, unknown>).serviceWorker
}

const config = (enabled: boolean) => json({ web_push_enabled: enabled, vapid_public_key: enabled ? 'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U' : null })

function setup(routes: Parameters<typeof fakeFetch>[0]) {
  const server = fakeFetch(routes)
  const api = new ApiClient('http://api.test', memoryStore('r0'), server.fetch)
  return { api, server }
}

afterEach(removeBrowser)

describe('browser push state', () => {
  it('says unsupported where the browser has no Push API (and never calls the server)', async () => {
    const { api, server } = setup({})
    const state = await pushState(api)
    expect(state.kind).toBe('unsupported')
    expect(server.calls).toEqual([])
  })

  it('is not-configured when the server has no push set up, and blocked when the browser denies it', async () => {
    installBrowser()
    expect((await pushState(setup({ 'POST /auth/session/refresh': json({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }), 'GET /push/config': config(false) }).api)).kind).toBe('not-configured')
    installBrowser({ permission: 'denied' })
    expect((await pushState(setup({ 'POST /auth/session/refresh': json({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }), 'GET /push/config': config(true) }).api)).kind).toBe('blocked')
  })

  it('is off until subscribed, then on', async () => {
    const b = installBrowser({ permission: 'granted' })
    const routes = { 'POST /auth/session/refresh': json({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }), 'GET /push/config': config(true) }
    expect((await pushState(setup(routes).api)).kind).toBe('off')
    b.subscription = { endpoint: ENDPOINT, toJSON: () => ({}), unsubscribe: vi.fn() }
    expect((await pushState(setup(routes).api)).kind).toBe('on')
  })
})

describe('enabling and disabling', () => {
  const base = { 'POST /auth/session/refresh': json({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }) }

  it('asks the browser for permission, subscribes with the server key, and registers exactly that subscription', async () => {
    const b = installBrowser()
    const bodies: unknown[] = []
    const { api } = setup({ ...base, 'GET /push/config': config(true), 'PUT /push/web-subscription': ({ body }) => (bodies.push(body), json(null, 204)) })
    const state = await enablePush(api)
    expect(state.kind).toBe('on')
    expect(b.requestPermission).toHaveBeenCalledTimes(1)
    const options = b.subscribe.mock.calls[0]![0] as { userVisibleOnly: boolean; applicationServerKey: Uint8Array }
    expect(options.userVisibleOnly).toBe(true)
    expect(options.applicationServerKey).toBeInstanceOf(Uint8Array)
    expect(options.applicationServerKey.length).toBe(65) // an uncompressed P-256 point
    expect(bodies).toEqual([{ endpoint: ENDPOINT, keys: KEYS }])
  })

  it('does nothing on the server when the person refuses the browser prompt', async () => {
    const b = installBrowser()
    b.requestPermission.mockImplementation(async () => 'denied')
    const { api, server } = setup({ ...base, 'GET /push/config': config(true) })
    expect((await enablePush(api)).kind).toBe('blocked')
    expect(b.subscribe).not.toHaveBeenCalled()
    expect(server.calls.some((c) => c.startsWith('PUT'))).toBe(false)
  })

  it('does not subscribe when the server has no push configured', async () => {
    const b = installBrowser()
    const { api } = setup({ ...base, 'GET /push/config': config(false) })
    expect((await enablePush(api)).kind).toBe('not-configured')
    expect(b.requestPermission).not.toHaveBeenCalled()
  })

  it('removes the subscription on the server first, then in the browser', async () => {
    const b = installBrowser({ permission: 'granted' })
    const order: string[] = []
    const sub = { endpoint: ENDPOINT, toJSON: () => ({}), unsubscribe: vi.fn(async () => (order.push('browser'), true)) }
    b.subscription = sub
    const { api } = setup({ ...base, 'POST /push/web-subscription/remove': ({ body }) => (order.push('server:' + (body as { endpoint: string }).endpoint), json(null, 204)) })
    await disablePush(api)
    expect(order).toEqual(['server:' + ENDPOINT, 'browser'])
  })

  it('still drops the browser subscription if the server call fails', async () => {
    const b = installBrowser({ permission: 'granted' })
    const sub = { endpoint: ENDPOINT, toJSON: () => ({}), unsubscribe: vi.fn(async () => true) }
    b.subscription = sub
    const { api } = setup({ ...base, 'POST /push/web-subscription/remove': json({ error: { code: 'INTERNAL_ERROR', message: 'x' } }, 500) })
    await expect(disablePush(api)).rejects.toBeTruthy()
    expect(sub.unsubscribe).toHaveBeenCalled()
  })
})

describe('PushSetup card', () => {
  const routes = { 'POST /auth/session/refresh': json({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }), 'GET /families': json({ families: [{ id: 'f', name: 'F', created_at: 'x', member_count: 1, device_count: 0, my_role: 'parent', status: 'active' }] }) }

  function mount(extra: Parameters<typeof fakeFetch>[0]) {
    const { api, server } = setup({ ...routes, ...extra })
    render(
      <AuthProvider api={api}>
        <PushSetup />
      </AuthProvider>,
    )
    return { api, server }
  }

  it('explains the limits honestly and offers to turn alerts on', async () => {
    installBrowser()
    mount({ 'GET /push/config': config(true) })
    const button = await screen.findByRole('button', { name: 'Turn on alerts for this browser' })
    expect(button).toBeEnabled()
    expect(screen.getByText(/never includes names, message text or a position/i)).toBeInTheDocument()
    expect(screen.getByText(/Piko is not an emergency service/i)).toBeInTheDocument()
  })

  it('turning on shows "On" with the caveat that a push is not proof of display', async () => {
    installBrowser()
    mount({ 'GET /push/config': config(true), 'PUT /push/web-subscription': json(null, 204) })
    await userEvent.click(await screen.findByRole('button', { name: 'Turn on alerts for this browser' }))
    expect(await screen.findByText(/not proof any single alert will be shown/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Turn off' })).toBeInTheDocument()
  })

  it('tells the person when nothing is set up or the browser cannot do it', async () => {
    mount({})
    expect(await screen.findByText(/only see alerts while this dashboard is open/i)).toBeInTheDocument()
  })

  it('shows blocked and not-configured states without a button that cannot work', async () => {
    installBrowser({ permission: 'denied' })
    mount({ 'GET /push/config': config(true) })
    expect(await screen.findByText(/blocked for this site/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Turn on/ })).toBeNull()
  })

  it('reports a server failure instead of pretending alerts are on', async () => {
    installBrowser()
    mount({ 'GET /push/config': config(true), 'PUT /push/web-subscription': json({ error: { code: 'INTERNAL_ERROR', message: 'x' } }, 500) })
    await userEvent.click(await screen.findByRole('button', { name: 'Turn on alerts for this browser' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/did not work/i)
  })
})

describe('urlBase64ToBytes', () => {
  it('decodes base64url with and without padding', () => {
    expect(Array.from(urlBase64ToBytes('AQID'))).toEqual([1, 2, 3])
    expect(Array.from(urlBase64ToBytes('AQI'))).toEqual([1, 2])
    expect(Array.from(urlBase64ToBytes('-_8'))).toEqual([251, 255])
  })
})

// ---- the service worker, run in a fake worker scope ------------------------------------------------------------
interface Shown {
  title: string
  options: Record<string, unknown>
}

function loadWorker() {
  const source = swSource
  const listeners: Record<string, (event: unknown) => void> = {}
  const shown: Shown[] = []
  const opened: string[] = []
  const navigated: string[] = []
  const self = {
    location: { origin: 'https://piko.example' },
    addEventListener: (name: string, fn: (event: unknown) => void) => (listeners[name] = fn),
    registration: { showNotification: async (title: string, options: Record<string, unknown>) => void shown.push({ title, options }) },
    clients: {
      matchAll: async () => [{ url: 'https://piko.example/', navigate: (u: string) => void navigated.push(u), focus: async () => undefined }],
      openWindow: async (u: string) => void opened.push(u),
    },
  }
  new Function('self', source)(self)
  const push = async (data: unknown) => {
    const waits: Promise<unknown>[] = []
    listeners.push!({ data: data === undefined ? null : { json: () => (typeof data === 'string' ? JSON.parse(data) : data) }, waitUntil: (p: Promise<unknown>) => waits.push(p) })
    await Promise.all(waits)
  }
  return { listeners, shown, push, opened, navigated, self }
}

describe('service worker', () => {
  it('shows a generic SOS notification that contains nothing private', async () => {
    const w = loadWorker()
    await w.push({ v: '1', type: 'sos_created', id: 'abc-123', name: 'Aarav', body: 'help me', latitude: 51.5 })
    expect(w.shown).toHaveLength(1)
    const text = JSON.stringify(w.shown[0])
    expect(w.shown[0]!.title).toBe('SOS alert')
    expect(text).not.toMatch(/Aarav|help me|51\.5/)
    expect(w.shown[0]!.options).toMatchObject({ tag: 'sos_created:abc-123', requireInteraction: true })
  })

  it('uses one tag per event so a duplicate push replaces the notification instead of stacking', async () => {
    const w = loadWorker()
    await w.push({ type: 'message', id: 'm1' })
    await w.push({ type: 'message', id: 'm1' })
    expect(new Set(w.shown.map((s) => s.options.tag)).size).toBe(1)
    expect(w.shown[0]!.options.requireInteraction).toBe(false)
  })

  it('shows a generic fallback for a malformed or empty payload instead of failing silently', async () => {
    const w = loadWorker()
    await w.push(undefined)
    await w.push('{not json')
      .catch(() => undefined)
    await w.push({ type: 'who-knows', id: 1 })
    expect(w.shown.length).toBeGreaterThanOrEqual(2)
    expect(w.shown.every((s) => s.title === 'Piko')).toBe(true)
  })

  it('opens the incident or the conversation when a notification is clicked, on this origin only', async () => {
    const w = loadWorker()
    const closed: boolean[] = []
    const click = async (url: string | undefined) => {
      const waits: Promise<unknown>[] = []
      w.listeners.notificationclick!({ notification: { close: () => closed.push(true), data: url ? { url } : null }, waitUntil: (p: Promise<unknown>) => waits.push(p) })
      await Promise.all(waits)
    }
    await w.push({ type: 'sos_update', id: 'i 1/2' })
    expect((w.shown[0]!.options.data as { url: string }).url).toBe('/sos?incident=i%201%2F2')
    await click('/sos?incident=i1')
    expect(w.navigated).toEqual(['/sos?incident=i1'])
    await click(undefined)
    expect(w.navigated.at(-1)).toBe('/alerts')
    expect(closed).toHaveLength(2)
  })

  it('makes no network request and keeps no state', () => {
    expect(swSource).not.toMatch(/fetch\(|XMLHttpRequest|localStorage|indexedDB|caches\./)
  })
})

beforeEach(() => {
  vi.stubGlobal('scrollTo', () => undefined)
})
