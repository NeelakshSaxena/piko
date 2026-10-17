import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { forwardRef } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatMessage, Incident } from '../api/types'
import { sortIncidents, locationNote, arrivalDelaySeconds, statusNotices } from '../lib/safety'
import { newId } from '../lib/newId'
import {
  CHILD_ID, DEVICE_ID, FAMILY_ID, a11yViolations, apiError, device, json, location, renderApp, sessionRoutes,
  type Routes,
} from '../test/helpers'

vi.mock('../components/Map', () => ({
  FleetMap: forwardRef(function FleetMap({ markers }: { markers: { id: string; fresh: boolean }[] }, _ref) {
    return <div data-testid="map" role="img" aria-label="map" data-fresh={markers.map((m) => String(m.fresh)).join(',')} />
  }),
  TileNotice: () => <p>tile notice</p>,
}))

const NOW = Date.now()
const iso = (secondsAgo: number) => new Date(NOW - secondsAgo * 1000).toISOString()

function incident(id: string, over: Partial<Incident> = {}): Incident {
  return {
    incident_id: id, device_id: DEVICE_ID, family_id: FAMILY_ID, status: 'open',
    triggered_at: iso(120), received_at: iso(118), message: null,
    location: { latitude: 40.7128, longitude: -74.006, accuracy_meters: 12, captured_at: iso(120), is_latest_known: false },
    acknowledged_at: null, resolved_at: null, parent_notes: null, ...over,
  }
}

const page = (incidents: Incident[]) => json({ incidents, total_count: incidents.length, has_more: false })

function message(id: string, over: Partial<ChatMessage> = {}): ChatMessage {
  return {
    message_id: id, device_id: DEVICE_ID, sender: 'device', body: 'hello there', sent_at: iso(60), received_at: iso(58),
    status: 'delivered', acknowledged_at: null, ...over,
  }
}
const msgPage = (messages: ChatMessage[]) => json({ messages, total_count: messages.length, has_more: false })

const base = (incidents: Incident[] = [], role: 'parent' | 'guardian' = 'parent'): Routes => ({
  ...sessionRoutes(role),
  'GET /sos/incidents': page(incidents),
  [`GET /members/${CHILD_ID}/location`]: json(location(30)),
  [`GET /devices/${DEVICE_ID}`]: json(device()),
})

describe('SOS Centre', () => {
  it('lists an open incident without calling it acknowledged, and says where the position came from', async () => {
    const view = renderApp('/sos', base([incident('i1', { message: 'help me' })]))
    expect(await screen.findByRole('heading', { name: 'SOS Centre' })).toBeInTheDocument()
    const card = await screen.findByRole('article', { name: /Aarav's phone/ })
    expect(card).toHaveTextContent('Open · not yet acknowledged')
    expect(card).not.toHaveTextContent(/Resolved|Acknowledged ·/)
    expect(card).toHaveTextContent('help me')
    expect(card).toHaveTextContent('Measured by the phone when the SOS was raised')
    expect(card).toHaveTextContent('Updated 2 min ago')
    expect(screen.getByText(/does not contact emergency services/i)).toBeInTheDocument()
    expect(await a11yViolations(view.container)).toEqual([])
  })

  it('labels a last-known position as such and a stale one as not current', async () => {
    renderApp('/sos', base([
      incident('i1', { location: { latitude: 1, longitude: 2, accuracy_meters: null, captured_at: iso(3600), is_latest_known: true } }),
    ]))
    const card = await screen.findByRole('article', { name: /Aarav's phone/ })
    expect(card).toHaveTextContent('Last known position, not sent with the SOS')
    expect(card).toHaveTextContent('Not current')
    expect(card).toHaveTextContent(/not current\. Do not treat it as where the child is right now/i)
    expect(card).toHaveTextContent('accuracy unknown')
    expect(screen.getByTestId('map')).toHaveAttribute('data-fresh', 'false')
  })

  it('shows an old recorded position as a record, never as a current one', async () => {
    renderApp('/sos', base([
      incident('i1', { status: 'resolved', location: { latitude: 1, longitude: 2, accuracy_meters: 5, captured_at: iso(3 * 86400), is_latest_known: false } }),
    ]))
    const card = await screen.findByRole('article', { name: /Aarav's phone/ })
    expect(card).toHaveTextContent(/Recorded position · captured 3 d ago/)
    expect(card).not.toHaveTextContent(/Updated|Not current/)
  })

  it('says plainly when there is no position, and when the SOS waited offline on the phone', async () => {
    renderApp('/sos', base([incident('i1', { location: null, triggered_at: iso(7200), received_at: iso(60) })]))
    const card = await screen.findByRole('article', { name: /Aarav's phone/ })
    expect(card).toHaveTextContent('No position was sent with this SOS')
    expect(card).toHaveTextContent(/Reached Piko 2 h after it was raised \(saved on the phone while offline\)/)
    expect(screen.queryByTestId('map')).toBeNull()
  })

  it('shows an app-wide banner and a navigation count while an SOS is open, on any page', async () => {
    renderApp('/', base([incident('i1')]))
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('1 SOS alert is open and not yet acknowledged')
    expect(within(banner).getByRole('link', { name: 'Open the SOS Centre' })).toHaveAttribute('href', '/sos')
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: /SOS Centre/ })).toHaveTextContent('1 open SOS')
  })

  it('shows no banner when nothing is open or only acknowledged incidents exist', async () => {
    renderApp('/', base([incident('i1', { status: 'acknowledged', acknowledged_at: iso(30) })]))
    await screen.findByRole('heading', { name: "Aarav's phone" })
    await waitFor(() => expect(screen.queryByText(/not yet acknowledged\./)).toBeNull())
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('does not treat a failed check as "no SOS"', async () => {
    renderApp('/', { ...base(), 'GET /sos/incidents': apiError(503, 'SERVICE_UNAVAILABLE') })
    expect(await screen.findByText(/could not check for SOS alerts/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Do not assume there are none/).length).toBeGreaterThan(0)
    const sosTile = await screen.findByRole('region', { name: 'SOS' })
    expect(sosTile).toHaveTextContent('Unknown')
    expect(sosTile).not.toHaveTextContent(/None open/)
  })

  it('acknowledges without resolving, and keeps the resolve action available', async () => {
    let status: Incident['status'] = 'open'
    const puts: unknown[] = []
    const routes: Routes = {
      ...base(),
      'GET /sos/incidents': () => page([incident('i1', { status, acknowledged_at: status === 'open' ? null : iso(1) })]),
      'PUT /sos/incidents/i1': ({ body }) => {
        puts.push(body)
        status = 'acknowledged'
        return json(incident('i1', { status }))
      },
    }
    renderApp('/sos', routes)
    await userEvent.click(await screen.findByRole('button', { name: 'Acknowledge' }))
    const card = await screen.findByText('Acknowledged · not resolved')
    expect(puts).toEqual([{ status: 'acknowledged' }])
    const article = card.closest('article')!
    expect(article).not.toHaveTextContent(/^Resolved/)
    expect(within(article).queryByRole('button', { name: 'Acknowledge' })).toBeNull()
    expect(within(article).getByRole('button', { name: /Mark as resolved/ })).toBeInTheDocument()
  })

  it('requires an explicit confirmation to resolve, and Cancel changes nothing', async () => {
    const puts: unknown[] = []
    renderApp('/sos', {
      ...base([incident('i1')]),
      'PUT /sos/incidents/i1': ({ body }) => {
        puts.push(body)
        return json(incident('i1', { status: 'resolved' }))
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: /Mark as resolved/ }))
    const group = screen.getByRole('group', { name: /Resolve the SOS from Aarav's phone/ })
    expect(group).toHaveTextContent('cannot be reopened')
    expect(puts).toEqual([])
    await userEvent.click(within(group).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('group')).toBeNull()
    expect(puts).toEqual([])
    await userEvent.click(await screen.findByRole('button', { name: /Mark as resolved/ }))
    await userEvent.type(screen.getByLabelText(/Optional note/), 'was a mistake')
    await userEvent.click(screen.getByRole('button', { name: 'Yes, mark as resolved' }))
    await waitFor(() => expect(puts).toEqual([{ status: 'resolved', notes: 'was a mistake' }]))
  })

  it('closes the confirmation once the incident is resolved, leaving no live buttons on it', async () => {
    let status: Incident['status'] = 'open'
    renderApp('/sos', {
      ...base(),
      'GET /sos/incidents': () => page([incident('i1', { status, resolved_at: status === 'resolved' ? iso(1) : null })]),
      'PUT /sos/incidents/i1': () => {
        status = 'resolved'
        return json(incident('i1', { status }))
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: /Mark as resolved/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Yes, mark as resolved' }))
    await waitFor(() => expect(screen.getByRole('article')).toHaveTextContent('Resolved'))
    expect(screen.queryByRole('group')).toBeNull()
    expect(screen.queryByRole('button', { name: /resolved|Acknowledge|Cancel/i })).toBeNull()
  })

  it('offers no actions on a resolved incident', async () => {
    renderApp('/sos', base([incident('i1', { status: 'resolved', resolved_at: iso(10), parent_notes: 'all fine' })]))
    const card = await screen.findByRole('article', { name: /Aarav's phone/ })
    expect(card).toHaveTextContent('Resolved')
    expect(card).toHaveTextContent('all fine')
    expect(within(card).queryByRole('button', { name: /Acknowledge|resolved/i })).toBeNull()
  })

  it('explains a conflict instead of pretending the change worked, and refreshes', async () => {
    let status: Incident['status'] = 'open'
    renderApp('/sos', {
      ...base(),
      'GET /sos/incidents': () => page([incident('i1', { status })]),
      'PUT /sos/incidents/i1': () => {
        status = 'resolved' // someone else resolved it first
        return apiError(409, 'CONFLICT')
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Acknowledge' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/changed while you were looking at it/)
    await waitFor(() => expect(screen.getByRole('article')).toHaveTextContent('Resolved'))
  })

  it('gives guardians a read-only view, and shows the server refusal if the API is called anyway', async () => {
    renderApp('/sos', base([incident('i1')], 'guardian'))
    const card = await screen.findByRole('article', { name: /Aarav's phone/ })
    expect(within(card).queryByRole('button', { name: /Acknowledge|resolved/i })).toBeNull()
    expect(card).toHaveTextContent('Guardians can view incidents but cannot acknowledge or resolve them')
  })

  it('shows a server refusal as a refusal', async () => {
    renderApp('/sos', { ...base([incident('i1')]), 'PUT /sos/incidents/i1': apiError(403, 'FORBIDDEN') })
    await userEvent.click(await screen.findByRole('button', { name: 'Acknowledge' }))
    expect(await screen.findByText(/server did not allow this/)).toBeInTheDocument()
  })

  it('keeps showing the last incidents with a warning when a refresh fails', async () => {
    let fail = false
    const { server } = renderApp('/sos', { ...base(), 'GET /sos/incidents': () => (fail ? apiError(503, 'SERVICE_UNAVAILABLE') : page([incident('i1')])) })
    await screen.findByRole('article')
    fail = true
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(await screen.findByText(/last ones that loaded and may be out of date/)).toBeInTheDocument()
    expect(screen.getByRole('article')).toBeInTheDocument()
    expect(server.calls.filter((c) => c === 'GET /sos/incidents').length).toBeGreaterThan(1)
  })

  it('has an honest empty state', async () => {
    renderApp('/sos', base([]))
    const heading = await screen.findByRole('heading', { name: 'No SOS incidents' })
    expect(heading.closest('section')).toHaveTextContent(/does not mean everyone is safe/)
  })

  it('shows a loading state, then an error with retry, when nothing has loaded', async () => {
    renderApp('/sos', { ...sessionRoutes(), 'GET /sos/incidents': apiError(500, 'INTERNAL_ERROR') })
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.queryByRole('article')).toBeNull()
  })

  it('does not put incident text in browser storage', async () => {
    renderApp('/sos', base([incident('i1', { message: 'SECRET-NOTE-123' })]))
    await screen.findByText('SECRET-NOTE-123')
    expect(JSON.stringify({ ...window.localStorage })).not.toContain('SECRET-NOTE-123')
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain('SECRET-NOTE-123')
  })

  it('selects the incident named in the link', async () => {
    renderApp('/sos?incident=i2', base([incident('i1'), incident('i2', { status: 'acknowledged' })]))
    await screen.findAllByRole('article')
    expect(document.querySelector('article.selected')).toHaveTextContent('Acknowledged · not resolved')
  })
})

describe('Messages', () => {
  it('shows a conversation with wording that claims only what the server recorded', async () => {
    const view = renderApp('/messages', {
      ...base(),
      [`GET /messages`]: msgPage([
        message('m3', { sender: 'parent', body: 'dinner?', status: 'delivered' }),
        message('m2', { sender: 'parent', body: 'ok?', status: 'acknowledged', acknowledged_at: iso(5) }),
        message('m1', { sender: 'device', body: 'on my way', status: 'delivered' }),
      ]),
    })
    expect(await screen.findByText('dinner?')).toBeInTheDocument()
    expect(screen.getAllByText(/has not confirmed seeing it/)).toHaveLength(1)
    expect(screen.getByText(/phone confirmed it was seen/)).toBeInTheDocument()
    expect(screen.getByText('Delivered to Piko. No parent has marked it as seen.')).toBeInTheDocument()
    expect(screen.queryByText(/^Seen$|has been read|read by/i)).toBeNull()
    expect(await a11yViolations(view.container)).toEqual([])
  })

  it('sends once with a stable id and shows it only after the server stored it', async () => {
    const stored: ChatMessage[] = []
    const posts: { message_id: string; device_id: string; body: string }[] = []
    renderApp('/messages', {
      ...base(),
      'GET /messages': () => msgPage([...stored].reverse()),
      'POST /messages': ({ body }) => {
        const b = body as { message_id: string; device_id: string; body: string; sent_at: string }
        posts.push(b)
        const m = message(b.message_id, { sender: 'parent', body: b.body })
        stored.push(m)
        return json(m, 201)
      },
    })
    await screen.findByText('No messages yet')
    await userEvent.type(screen.getByLabelText(/Message to Aarav's phone/), 'see you at 6')
    await userEvent.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByText('see you at 6')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/has not confirmed seeing it/)).toBeInTheDocument())
    expect(posts).toHaveLength(1)
    expect(posts[0]!.device_id).toBe(DEVICE_ID)
    expect(posts[0]!.message_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(screen.queryByText(/Sending…/)).toBeNull()
  })

  it('keeps a failed message visible and retries with the same id, so it cannot be stored twice', async () => {
    const stored = new Map<string, ChatMessage>()
    const ids: string[] = []
    let failNext = true
    renderApp('/messages', {
      ...base(),
      'GET /messages': () => msgPage([...stored.values()]),
      'POST /messages': ({ body }) => {
        const b = body as { message_id: string; body: string }
        ids.push(b.message_id)
        if (failNext) {
          failNext = false
          return apiError(503, 'SERVICE_UNAVAILABLE')
        }
        stored.set(b.message_id, message(b.message_id, { sender: 'parent', body: b.body }))
        return json(stored.get(b.message_id), 201)
      },
    })
    await screen.findByText('No messages yet')
    await userEvent.type(screen.getByLabelText(/Message to/), 'are you ok')
    await userEvent.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByText(/Not sent\./)).toBeInTheDocument()
    expect(screen.getByText('are you ok')).toBeInTheDocument()
    expect(screen.queryByText(/Delivered to the Piko server/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(stored.size).toBe(1))
    expect(new Set(ids).size).toBe(1) // both attempts carried the same id
    await waitFor(() => expect(screen.queryByText(/Not sent\./)).toBeNull())
    expect(screen.getAllByText('are you ok')).toHaveLength(1)
  })

  it('does not put message text in browser storage', async () => {
    renderApp('/messages', { ...base(), 'GET /messages': msgPage([message('m1', { body: 'PRIVATE-BODY-987' })]) })
    await screen.findByText('PRIVATE-BODY-987')
    expect(JSON.stringify({ ...window.localStorage })).not.toContain('PRIVATE-BODY-987')
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain('PRIVATE-BODY-987')
  })

  it('marks a child message as seen only when a parent presses the button', async () => {
    const acks: string[] = []
    let status: ChatMessage['status'] = 'delivered'
    renderApp('/messages', {
      ...base(),
      'GET /messages': () => msgPage([message('m1', { status, acknowledged_at: status === 'acknowledged' ? iso(1) : null })]),
      'POST /messages/m1/ack': () => {
        acks.push('m1')
        status = 'acknowledged'
        return json(message('m1', { status }))
      },
    })
    await screen.findByText('hello there')
    expect(acks).toEqual([]) // viewing is not acknowledging
    await userEvent.click(screen.getByRole('button', { name: 'Mark as seen' }))
    expect(await screen.findByText(/Marked as seen by a parent/)).toBeInTheDocument()
    expect(acks).toEqual(['m1'])
    expect(screen.queryByRole('button', { name: 'Mark as seen' })).toBeNull()
  })

  it('shows guardians the conversation without a composer or seen button', async () => {
    renderApp('/messages', { ...base([], 'guardian'), 'GET /messages': msgPage([message('m1')]) })
    await screen.findByText('hello there')
    expect(screen.queryByRole('button', { name: 'Send message' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Mark as seen' })).toBeNull()
    expect(screen.getByText(/Guardians can read this conversation but cannot send/)).toBeInTheDocument()
  })

  it('notes messages that reached Piko late and rejects an empty draft', async () => {
    renderApp('/messages', { ...base(), 'GET /messages': msgPage([message('m1', { sent_at: iso(3 * 3600), received_at: iso(60) })]) })
    expect(await screen.findByText(/after it was sent \(saved on the phone while offline\)/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
  })

  it('shows an error with retry when messages cannot load', async () => {
    renderApp('/messages', { ...base(), 'GET /messages': apiError(503, 'SERVICE_UNAVAILABLE') })
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('says so when no phone is linked', async () => {
    renderApp('/messages', sessionRoutes('parent', false))
    expect(await screen.findByText('No phone is linked yet')).toBeInTheDocument()
  })

  it('explains that the phone is not pushed to', async () => {
    renderApp('/messages', { ...base(), 'GET /messages': msgPage([]) })
    expect(await screen.findByText(/does not push them to the phone/)).toBeInTheDocument()
  })
})

describe('Alerts', () => {
  it('combines SOS, unseen child messages and derived phone notices, most urgent first, with links', async () => {
    const view = renderApp('/alerts', {
      ...base([incident('i1'), incident('i2', { status: 'resolved', resolved_at: iso(5) })]),
      'GET /messages': msgPage([message('m1', { sender: 'device', status: 'delivered' })]),
      [`GET /devices/${DEVICE_ID}`]: json(device({ connectivity_status: 'offline', battery_percent: 9, battery_is_charging: false })),
      [`GET /members/${CHILD_ID}/location`]: json(location(1800)),
    })
    await screen.findByRole('heading', { name: 'SOS from Aarav\'s phone', level: 2 }).catch(() => undefined)
    const list = await screen.findByRole('list', { name: 'Alerts' })
    await waitFor(() => expect(within(list).getAllByRole('listitem').length).toBeGreaterThanOrEqual(5))
    const items = within(list).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Needs action')
    expect(items[0]).toHaveTextContent('SOS from')
    expect(within(items[0]!).getByRole('link', { name: 'Open the incident' })).toHaveAttribute('href', '/sos?incident=i1')
    expect(list).toHaveTextContent('1 message from Aarav\'s phone not marked as seen')
    expect(list).toHaveTextContent('has gone quiet')
    expect(list).toHaveTextContent("battery was low")
    expect(list).toHaveTextContent('Phone status (derived)')
    expect(list).toHaveTextContent('No current location for')
    expect(screen.getByText(/These are not push notifications/)).toBeInTheDocument()
    const link = within(list).getByRole('link', { name: 'Open the conversation' })
    expect(link).toHaveAttribute('href', `/messages?member=${CHILD_ID}`)
    expect(await a11yViolations(view.container)).toEqual([])
  })

  it('says what failed instead of dropping a source silently', async () => {
    renderApp('/alerts', { ...base([incident('i1')]), 'GET /messages': apiError(503, 'SERVICE_UNAVAILABLE') })
    expect(await screen.findByText(/Messages from Aarav's phone could not be loaded/)).toBeInTheDocument()
    expect(screen.getByText(/SOS from/)).toBeInTheDocument()
  })

  it('has an empty state that does not claim safety', async () => {
    renderApp('/alerts', { ...base(), 'GET /messages': msgPage([]) })
    const empty = await screen.findByRole('heading', { name: 'No alerts right now' })
    expect(empty.closest('section')).toHaveTextContent(/not proof that a child is safe/)
  })

  it('shows an error when SOS cannot be read', async () => {
    renderApp('/alerts', { ...base(), 'GET /sos/incidents': apiError(503, 'SERVICE_UNAVAILABLE'), 'GET /messages': msgPage([]) })
    expect(await screen.findAllByRole('button', { name: 'Try again' })).not.toHaveLength(0)
    expect(screen.queryByRole('heading', { name: 'No alerts right now' })).toBeNull()
  })
})

describe('safety helpers', () => {
  it('sorts unresolved first, open before acknowledged, then newest', () => {
    const list = sortIncidents([
      incident('r', { status: 'resolved', triggered_at: iso(10) }),
      incident('a', { status: 'acknowledged', triggered_at: iso(20) }),
      incident('o-old', { status: 'open', triggered_at: iso(500) }),
      incident('o-new', { status: 'open', triggered_at: iso(30) }),
    ])
    expect(list.map((i) => i.incident_id)).toEqual(['o-new', 'o-old', 'a', 'r'])
  })

  it('classifies fresh, stale, historical and missing positions against now', () => {
    const at = (s: number, latest = false) =>
      ({ location: { latitude: 1, longitude: 2, accuracy_meters: null, captured_at: iso(s), is_latest_known: latest } }) as Pick<Incident, 'location'>
    expect(locationNote(at(30), NOW)).toMatchObject({ kind: 'sent-with-sos', currency: 'fresh' })
    expect(locationNote(at(301), NOW)).toMatchObject({ currency: 'stale' })
    expect(locationNote(at(86_401, true), NOW)).toMatchObject({ kind: 'latest-known', currency: 'historical' })
    expect(locationNote({ location: null }, NOW)).toEqual({ kind: 'none', currency: 'none', ageSeconds: null })
  })

  it('measures how long an SOS waited before reaching the server, never negative', () => {
    expect(arrivalDelaySeconds({ triggered_at: iso(100), received_at: iso(40) })).toBe(60)
    expect(arrivalDelaySeconds({ triggered_at: iso(40), received_at: iso(100) })).toBe(0)
  })

  it('derives notices only from what the phone reported', () => {
    const child = { id: 'c', name: 'Kid' }
    expect(statusNotices(child, device({ connectivity_status: 'online', battery_percent: 80 }), location(10), NOW)).toEqual([])
    expect(statusNotices(child, device({ battery_percent: 10, battery_is_charging: true }), location(10), NOW)).toEqual([])
    expect(statusNotices(child, device({ battery_percent: 10, battery_is_charging: null }), location(10), NOW)).toEqual([])
    expect(statusNotices(child, device({ battery_percent: 10, battery_is_charging: false }), location(10), NOW).map((n) => n.id)).toEqual(['battery:c'])
    expect(statusNotices(child, device({ connectivity_status: 'unknown' }), null, NOW).map((n) => n.id)).toEqual(['never:c'])
  })

  it('makes a v4 id even where crypto.randomUUID is unavailable (plain http)', () => {
    const original = crypto.randomUUID
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true })
    try {
      const a = newId()
      expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
      expect(newId()).not.toBe(a)
    } finally {
      Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true })
    }
  })
})

describe('banner is not computed from a truncated page (audit F-03)', () => {
  it('counts an open SOS that is older than the newest hundred', async () => {
    const recent = Array.from({ length: 100 }, (_, n) => incident(`r${n}`, { status: 'resolved', resolved_at: iso(5), received_at: iso(10 + n) }))
    const oldOpen = incident('old-open', { received_at: iso(86_400 * 5), triggered_at: iso(86_400 * 5) })
    const seen: string[] = []
    renderApp('/', {
      ...base(),
      'GET /sos/incidents': ({ url }) => {
        seen.push(url.search)
        return url.searchParams.get('status') === 'open'
          ? json({ incidents: [oldOpen], total_count: 1, has_more: false })
          : json({ incidents: recent, total_count: 101, has_more: true })
      },
    })
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('1 SOS alert is open')
    expect(seen.some((s) => s.includes('status=open'))).toBe(true)
  })

  it('tells the person when older incidents are not loaded', async () => {
    const recent = Array.from({ length: 3 }, (_, n) => incident(`r${n}`, { status: 'resolved', resolved_at: iso(5), received_at: iso(10 + n) }))
    renderApp('/sos', {
      ...base(),
      'GET /sos/incidents': ({ url }) =>
        url.searchParams.get('status') === 'open' ? json({ incidents: [], total_count: 0, has_more: false }) : json({ incidents: recent, total_count: 250, has_more: true }),
    })
    expect(await screen.findByText(/Older\s+acknowledged or resolved incidents are not listed here/)).toBeInTheDocument()
    expect(screen.getByText(/3 of 250 loaded/)).toBeInTheDocument()
  })

  it('shows the server count when there are more open incidents than one page holds', async () => {
    const open = Array.from({ length: 100 }, (_, n) => incident(`o${n}`, { received_at: iso(10 + n) }))
    renderApp('/', {
      ...base(),
      'GET /sos/incidents': json({ incidents: open, total_count: 130, has_more: true }),
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('130 SOS alerts are open')
  })
})

describe('XSS and control text in the pages', () => {
  it('renders markup in a note or message as inert text', async () => {
    const evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>'
    renderApp('/sos', base([incident('i1', { message: evil, parent_notes: evil })]))
    await screen.findByRole('article')
    expect(document.querySelector('article img, article script')).toBeNull()
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined()
    expect(screen.getAllByText(evil, { exact: false }).length).toBeGreaterThan(0)
  })

  it('renders markup in a message body as inert text', async () => {
    const evil = '<img src=x onerror="window.__pwned=3">'
    renderApp('/messages', { ...base(), 'GET /messages': msgPage([message('m1', { body: evil })]) })
    await screen.findByText(evil)
    expect(document.querySelector('.chat img')).toBeNull()
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined()
  })

  it('keeps message and note text out of every browser storage key and value', async () => {
    renderApp('/messages', { ...base(), 'GET /messages': msgPage([message('m1', { body: 'STORAGE-PROBE-555' })]) })
    await screen.findByText('STORAGE-PROBE-555')
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (let i = 0; i < store.length; i++) {
        const key = store.key(i)!
        expect(key + String(store.getItem(key))).not.toContain('STORAGE-PROBE-555')
      }
    }
  })
})

describe('Messages: who can read', () => {
  it('tells parents that guardians can read the conversation', async () => {
    renderApp('/messages', { ...base(), 'GET /messages': msgPage([]) })
    expect(await screen.findByText(/Parents and guardians in this family can read this\s+conversation/)).toBeInTheDocument()
  })
})
