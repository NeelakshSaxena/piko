import { render } from '@testing-library/react'
import axe from 'axe-core'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { AppRoutes } from '../App'
import { ApiClient, type RefreshStore, type StoredAccess } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import type { DeviceDetail, FamilyDetail, FamilySummary, HistoryPage, MemberLocation, Role } from '../api/types'

export function memoryStore(
  initial: string | null = null,
  access: StoredAccess | null = null,
): RefreshStore & { value: string | null; access: StoredAccess | null } {
  const store = {
    value: initial,
    access,
    get: () => store.value,
    set: (t: string | null) => {
      store.value = t
    },
    getAccess: () => store.access,
    setAccess: (a: StoredAccess | null) => {
      store.access = a
    },
  }
  return store
}

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

export function apiError(status: number, code: string, message = 'nope'): Response {
  return json({ error: { code, message, request_id: 'req-test', timestamp: 'x' } }, status)
}

export type Handler = (req: { url: URL; init: RequestInit; body: unknown }) => Response | Promise<Response>
export type Routes = Record<string, Handler | Response>

/** A fake server keyed by "METHOD /path" (without /api/v1). Unlisted requests fail the test loudly. */
export function fakeFetch(routes: Routes) {
  const calls: string[] = []
  const impl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input))
    const key = `${init.method ?? 'GET'} ${url.pathname.replace('/api/v1', '')}`
    calls.push(key)
    const route = routes[key]
    if (!route) throw new Error(`unexpected request: ${key}`)
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    return route instanceof Response ? route.clone() : route({ url, init, body })
  })
  return { fetch: impl as unknown as typeof fetch, calls, impl }
}

export const FAMILY_ID = 'fam-1'
export const CHILD_ID = 'member-child'
export const DEVICE_ID = 'dev-1'

export function summary(role: Role = 'parent'): FamilySummary {
  return { id: FAMILY_ID, name: 'Test Family', created_at: '2026-10-01T00:00:00Z', member_count: 3, device_count: 1, my_role: role, status: 'active' }
}

export function detail(role: Role = 'parent', withChild = true): FamilyDetail {
  return {
    id: FAMILY_ID,
    name: 'Test Family',
    created_at: '2026-10-01T00:00:00Z',
    my_role: role,
    members: [
      { id: 'member-parent', email: 'parent@example.com', name: 'Pat Parent', role: 'parent', joined_at: '2026-10-01T00:00:00Z', status: 'active' },
      ...(withChild
        ? [{ id: CHILD_ID, email: null, name: "Aarav's phone", role: 'child' as Role, joined_at: '2026-10-02T00:00:00Z', status: 'active' as const }]
        : []),
    ],
    devices: withChild
      ? [{ id: DEVICE_ID, name: "Aarav's phone", device_type: 'android', owner_member_id: CHILD_ID, paired_at: '2026-10-02T00:00:00Z', last_seen: new Date(Date.now() - 60_000).toISOString(), status: 'active' }]
      : [],
  }
}

export function device(overrides: Partial<DeviceDetail> = {}): DeviceDetail {
  return {
    id: DEVICE_ID, family_id: FAMILY_ID, name: "Aarav's phone", owner_member_id: CHILD_ID, device_model: 'Pixel 7',
    android_version: '16', app_version: '0.4.0', paired_at: '2026-10-02T00:00:00Z',
    last_activity: new Date(Date.now() - 60_000).toISOString(), connectivity_status: 'online',
    battery_percent: 81, battery_updated_at: new Date(Date.now() - 120_000).toISOString(),
    battery_is_charging: false, network_type: 'wifi', network_updated_at: new Date(Date.now() - 90_000).toISOString(), status: 'active', ...overrides,
  }
}

export function location(ageSeconds: number | null, extra: Partial<MemberLocation> = {}): MemberLocation {
  if (ageSeconds === null) {
    return { member_id: CHILD_ID, device_id: DEVICE_ID, available: false, freshness: 'unknown', freshness_seconds: null, device_status: 'unknown' }
  }
  const at = new Date(Date.now() - ageSeconds * 1000).toISOString()
  return {
    member_id: CHILD_ID, device_id: DEVICE_ID, available: true, freshness: ageSeconds <= 300 ? 'fresh' : 'stale',
    freshness_seconds: ageSeconds, device_status: 'online', coordinates: { latitude: 40.7128, longitude: -74.006 },
    accuracy_meters: 15, occurred_at: at, received_at: at, ...extra,
  }
}

export function history(items: HistoryPage['history'], total = items.length, more = false): HistoryPage {
  return { member_id: CHILD_ID, device_status: 'online', history: items, total_count: total, has_more: more }
}

export function sessionRoutes(role: Role = 'parent', withChild = true): Routes {
  return {
    'POST /auth/session/refresh': json({ access_token: 'a1', refresh_token: 'r1', expires_in: 3600 }),
    'GET /families': json({ families: [summary(role)] }),
    [`GET /families/${FAMILY_ID}`]: json(detail(role, withChild)),
    'GET /sos/incidents': json({ incidents: [], total_count: 0, has_more: false }),
  }
}

/** Renders the real app routes against a fake server with an already-signed-in (refresh token present) browser. */
export function renderApp(path: string, routes: Routes, opts: { signedIn?: boolean } = {}) {
  const { signedIn = true } = opts
  const server = fakeFetch(routes)
  const store = memoryStore(signedIn ? 'r0' : null)
  const api = new ApiClient('http://api.test', store, server.fetch)
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider api={api}>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  )
  return { ...view, api, store, server }
}

/** Accessibility violations per axe-core. Colour contrast needs real rendering, so it is checked in the browser, not jsdom. */
export async function a11yViolations(container: HTMLElement) {
  const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join('; ')})`)
}
