import type {
  AcceptResult,
  DeviceDetail,
  ErrorCode,
  FamilyDetail,
  FamilySummary,
  ChatMessage,
  HistoryPage,
  Incident,
  IncidentPage,
  InvitableRole,
  MessagePage,
  PushConfig,
  SosStatus,
  InviteResult,
  MemberLocation,
  PairingCode,
  RefreshResponse,
  SessionResponse,
  WebPushSubscriptionBody,
} from './types'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ErrorCode | 'NETWORK' | 'UNKNOWN',
    message: string,
    readonly requestId?: string,
    readonly retryAfterSeconds?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  /** The server refused this caller (as opposed to the data being absent or the network failing). */
  get denied(): boolean {
    return this.status === 403 || this.code === 'FORBIDDEN'
  }
}

export interface StoredAccess {
  token: string
  expiresAtMs: number
}

/**
 * Where tokens live: both tokens are in sessionStorage (per tab), so a script running on the page could read them; the CSP is the mitigation. Per-tab on purpose: refresh tokens rotate, so two tabs sharing one would revoke
 * each other. The short-lived access token is kept too, so a page reload does not need a refresh;
 * refreshing on every load meant a reload that interrupted a refresh replayed a rotated token and
 * ended the session.
 */
export interface RefreshStore {
  get(): string | null
  set(token: string | null): void
  getAccess(): StoredAccess | null
  setAccess(access: StoredAccess | null): void
}

function readJson(key: string): unknown {
  try {
    const raw = window.sessionStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export const sessionRefreshStore: RefreshStore = {
  get: () => {
    try {
      return window.sessionStorage.getItem('piko.refresh')
    } catch {
      return null
    }
  },
  set: (token) => {
    try {
      if (token === null) window.sessionStorage.removeItem('piko.refresh')
      else window.sessionStorage.setItem('piko.refresh', token)
    } catch {
      /* storage unavailable: the user simply signs in again after a reload */
    }
  },
  getAccess: () => {
    const value = readJson('piko.access') as Partial<StoredAccess> | null
    return value && typeof value.token === 'string' && typeof value.expiresAtMs === 'number'
      ? { token: value.token, expiresAtMs: value.expiresAtMs }
      : null
  },
  setAccess: (access) => {
    try {
      if (access === null) window.sessionStorage.removeItem('piko.access')
      else window.sessionStorage.setItem('piko.access', JSON.stringify(access))
    } catch {
      /* storage unavailable */
    }
  },
}

/** A reply of the wrong shape is an error, never "nothing there": an empty list would read as "no incidents". */
function requireList<T extends object>(page: T, key: keyof T): T {
  if (typeof page !== 'object' || page === null || !Array.isArray(page[key])) {
    throw new ApiError(200, 'UNKNOWN', 'The server sent a reply Piko did not understand.')
  }
  return page
}

type Query = Record<string, string | number | undefined>

const REQUEST_TIMEOUT_MS = 15_000

/**
 * Typed fetch wrapper. The access token is held in memory and copied to sessionStorage (see RefreshStore). A 401 triggers exactly one refresh
 * (shared by all concurrent callers, because a second use of a rotated refresh token would revoke the
 * session) and one retry of the original request.
 */
export class ApiClient {
  private access: string | null = null
  private refreshing: Promise<void> | null = null
  private restoring: Promise<boolean> | null = null
  /** Called when the session cannot be continued (refresh refused). */
  onSessionLost: () => void = () => undefined

  constructor(
    private readonly base: string,
    private readonly store: RefreshStore = sessionRefreshStore,
    private readonly fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  get hasSession(): boolean {
    return this.access !== null || this.store.get() !== null
  }

  // ---- session ----
  async login(email: string, password: string): Promise<SessionResponse> {
    const session = await this.request<SessionResponse>('POST', '/auth/session', {
      body: { email, password },
      auth: false,
    })
    this.setAccessToken(session.access_token, session.expires_in)
    this.store.set(session.refresh_token)
    return session
  }

  /** Resumes a session after a page reload. Safe to call repeatedly (React StrictMode runs effects twice). */
  restore(): Promise<boolean> {
    if (!this.restoring) {
      const attempt = this.doRestore().finally(() => {
        this.restoring = null // only memoised while in flight
      })
      this.restoring = attempt
    }
    return this.restoring
  }

  private async doRestore(): Promise<boolean> {
    if (this.access) return true
    if (!this.store.get()) return false
    const saved = this.store.getAccess()
    if (saved && saved.expiresAtMs > Date.now()) {
      this.access = saved.token // still valid: no refresh, so a reload cannot interrupt a token rotation
      return true
    }
    try {
      await this.refresh()
      return true
    } catch (error) {
      if (error instanceof ApiError && error.code === 'NETWORK') throw error
      return false
    }
  }

  async logout(): Promise<void> {
    try {
      if (this.access) await this.request<void>('POST', '/auth/session/revoke', { retry: false })
    } catch {
      /* best effort: local state is cleared regardless */
    }
    this.clear()
  }

  private clear(): void {
    this.access = null
    this.store.set(null)
    this.store.setAccess(null)
  }

  /** Remembers the access token with a safety margin so it is never used in its last minute. */
  private setAccessToken(token: string, expiresInSeconds: number): void {
    this.access = token
    this.store.setAccess({ token, expiresAtMs: Date.now() + Math.max(0, expiresInSeconds - 60) * 1000 })
  }

  /** One refresh at a time, shared by every caller: reusing a rotated token revokes the session. */
  private refresh(): Promise<void> {
    if (!this.refreshing) {
      const attempt = this.doRefresh().finally(() => {
        this.refreshing = null
      })
      this.refreshing = attempt
    }
    return this.refreshing
  }

  private async doRefresh(): Promise<void> {
    const token = this.store.get()
    if (!token) throw new ApiError(401, 'AUTH_REQUIRED', 'No session.')
    try {
      const next = await this.send<RefreshResponse>('POST', '/auth/session/refresh', { bearer: token })
      // Persist the rotated token before anything else can use or lose it.
      this.store.set(next.refresh_token)
      this.setAccessToken(next.access_token, next.expires_in)
    } catch (error) {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 429) {
        this.clear()
        this.onSessionLost()
      }
      throw error
    }
  }

  // ---- requests ----
  private async request<T>(
    method: string,
    path: string,
    opts: { body?: unknown; query?: Query; auth?: boolean; retry?: boolean } = {},
  ): Promise<T> {
    const { auth = true, retry = true } = opts
    if (auth && !this.access && this.store.get()) {
      const saved = this.store.getAccess()
      if (saved && saved.expiresAtMs > Date.now()) this.access = saved.token
      else await this.refresh()
    }
    try {
      return await this.send<T>(method, path, { ...opts, bearer: auth ? this.access : null })
    } catch (error) {
      const expired = error instanceof ApiError && error.status === 401 && auth && retry
      if (!expired) throw error
      await this.refresh() // throws, and signals onSessionLost, if the session is really gone
      return this.send<T>(method, path, { ...opts, bearer: this.access })
    }
  }

  private async send<T>(
    method: string,
    path: string,
    opts: { body?: unknown; query?: Query; bearer?: string | null },
  ): Promise<T> {
    const url = new URL(`${this.base}/api/v1${path}`)
    for (const [key, value] of Object.entries(opts.query ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value))
    }
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
    if (opts.bearer) headers.Authorization = `Bearer ${opts.bearer}`
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
    let response: Response
    try {
      response = await this.fetchImpl(url, {
        method,
        headers,
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        signal: controller.signal,
        credentials: 'omit',
        cache: 'no-store',
        redirect: 'error',
      })
    } catch {
      throw new ApiError(0, 'NETWORK', 'Cannot reach the Piko server.')
    } finally {
      clearTimeout(timer)
    }
    if (response.status === 204) return undefined as T
    const text = await response.text()
    let payload: unknown = null
    try {
      payload = text ? JSON.parse(text) : null
    } catch {
      /* non-JSON body: handled below */
    }
    if (!response.ok) {
      const err = (payload as { error?: { code?: ErrorCode; message?: string; request_id?: string } } | null)?.error
      const retryAfter = Number(response.headers.get('Retry-After'))
      throw new ApiError(
        response.status,
        err?.code ?? 'UNKNOWN',
        err?.message ?? `The server answered HTTP ${response.status}.`,
        err?.request_id,
        Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
      )
    }
    if (payload === null) throw new ApiError(response.status, 'UNKNOWN', 'The server sent an empty reply.')
    return payload as T
  }

  // ---- endpoints ----
  async families(): Promise<FamilySummary[]> {
    return (await this.request<{ families: FamilySummary[] }>('GET', '/families')).families
  }
  family(id: string): Promise<FamilyDetail> {
    return this.request('GET', `/families/${id}`)
  }
  device(id: string): Promise<DeviceDetail> {
    return this.request('GET', `/devices/${id}`)
  }
  revokeDevice(id: string): Promise<void> {
    return this.request('DELETE', `/devices/${id}`)
  }
  memberLocation(memberId: string): Promise<MemberLocation> {
    return this.request('GET', `/members/${memberId}/location`)
  }
  memberHistory(
    memberId: string,
    q: { limit?: number; offset?: number; start_time?: string; end_time?: string; event_type?: string },
  ): Promise<HistoryPage> {
    return this.request('GET', `/members/${memberId}/history`, { query: q })
  }
  async sosIncidents(q: { status?: SosStatus; limit?: number; offset?: number } = {}): Promise<IncidentPage> {
    const page = await this.request<IncidentPage>('GET', '/sos/incidents', { query: q })
    return requireList(page, 'incidents')
  }
  updateSos(id: string, status: 'acknowledged' | 'resolved', notes?: string): Promise<Incident> {
    return this.request('PUT', `/sos/incidents/${id}`, { body: { status, ...(notes ? { notes } : {}) } })
  }
  async messages(deviceId: string, q: { limit?: number; offset?: number } = {}): Promise<MessagePage> {
    const page = await this.request<MessagePage>('GET', '/messages', { query: { device_id: deviceId, ...q } })
    return requireList(page, 'messages')
  }
  /** `messageId` is chosen by the caller and reused on retry, so a retry can never create a second message. */
  sendMessage(m: { messageId: string; deviceId: string; body: string; sentAt: string }): Promise<ChatMessage> {
    return this.request('POST', '/messages', { body: { message_id: m.messageId, device_id: m.deviceId, body: m.body, sent_at: m.sentAt } })
  }
  acknowledgeMessage(id: string): Promise<ChatMessage> {
    return this.request('POST', `/messages/${id}/ack`)
  }
  pushConfig(): Promise<PushConfig> {
    return this.request('GET', '/push/config')
  }
  registerWebPush(subscription: WebPushSubscriptionBody): Promise<void> {
    return this.request('PUT', '/push/web-subscription', { body: subscription })
  }
  removeWebPush(endpoint: string): Promise<void> {
    return this.request('POST', '/push/web-subscription/remove', { body: { endpoint } })
  }
  createPairingCode(): Promise<PairingCode> {
    return this.request('POST', '/devices/pairing-code')
  }
  invite(familyId: string, email: string, role: InvitableRole): Promise<InviteResult> {
    return this.request('POST', `/families/${familyId}/members`, { body: { email, role } })
  }
  acceptInvite(code: string, email: string, password: string, fullName?: string): Promise<AcceptResult> {
    return this.request('POST', '/invitations/accept', {
      auth: false,
      body: { invite_code: code, email, password, full_name: fullName || undefined },
    })
  }
}
