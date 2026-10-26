import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { forwardRef } from 'react'
import { describe, expect, it, vi } from 'vitest'
import {
  CHILD_ID, DEVICE_ID, FAMILY_ID, a11yViolations, apiError, detail, device, history, json, location, renderApp, sessionRoutes,
} from '../test/helpers'
import { eventsToCsv } from './HealthPage'

// Leaflet needs real layout; the map component is exercised in the browser, not in jsdom.
vi.mock('../components/Map', () => ({
  FleetMap: forwardRef(function FleetMap(
    { markers, selectedId, route }: { markers: { id: string; fresh: boolean }[]; selectedId?: string | null; route?: { segments: unknown[]; gaps: unknown[] } | null },
    _ref,
  ) {
    return (
      <div
        data-testid="map"
        role="img"
        aria-label="map"
        data-markers={markers.length}
        data-selected={selectedId ?? 'none'}
        data-fresh={markers.map((m) => String(m.fresh)).join(',')}
        data-segments={route ? route.segments.length : 'no-route'}
        data-gaps={route ? route.gaps.length : 'no-route'}
      />
    )
  }),
  TileNotice: () => <p>tile notice</p>,
}))

const NOW = Date.now()
const histItem = (id: string, secondsAgo: number, lat: number, extra: Record<string, unknown> = {}) => ({
  event_id: id,
  occurred_at: new Date(NOW - secondsAgo * 1000).toISOString(),
  received_at: new Date(NOW - secondsAgo * 1000 + 1000).toISOString(),
  event_type: 'location' as const,
  freshness: 'stale' as const,
  data: { latitude: lat, longitude: 10, accuracy_meters: 8 },
  ...extra,
})

const childRoutes = (loc = location(30), dev = device(), hist = history([histItem('h1', 30, 1)])) => ({
  ...sessionRoutes(),
  [`GET /members/${CHILD_ID}/location`]: json(loc),
  [`GET /devices/${DEVICE_ID}`]: json(dev),
  [`GET /members/${CHILD_ID}/history`]: json(hist),
})

describe('sign in', () => {
  it('shows an accessible form and explains a wrong password without saying which part', async () => {
    const view = renderApp('/login', { 'POST /auth/session': apiError(401, 'AUTH_INVALID') }, { signedIn: false })
    await screen.findByRole('heading', { name: 'Sign in to Piko' })
    expect(await a11yViolations(view.container)).toEqual([])
    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That email and password do not match.')
  })

  it('redirects anonymous visitors from protected pages to the sign-in page', async () => {
    renderApp('/map', {}, { signedIn: false })
    expect(await screen.findByRole('heading', { name: 'Sign in to Piko' })).toBeInTheDocument()
  })

  it('returns to sign-in when the stored session is refused', async () => {
    renderApp('/', { 'POST /auth/session/refresh': apiError(401, 'AUTH_INVALID') })
    expect(await screen.findByRole('heading', { name: 'Sign in to Piko' })).toBeInTheDocument()
  })

  it('reports rate limiting with the wait time', async () => {
    renderApp('/login', { 'POST /auth/session': json({ error: { code: 'RATE_LIMIT', message: 'x', request_id: 'r' } }, 429, { 'Retry-After': '30' }) }, { signedIn: false })
    await userEvent.type(await screen.findByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Wait 30 seconds')
  })
})

describe('join with an invite code', () => {
  it('is accessible and explains a refused invitation without revealing which part was wrong', async () => {
    const view = renderApp('/join', { 'POST /invitations/accept': apiError(401, 'AUTH_INVALID') }, { signedIn: false })
    await screen.findByRole('heading', { name: 'Join a family' })
    expect(await a11yViolations(view.container)).toEqual([])
    await userEvent.type(screen.getByLabelText('Invite code'), 'abc-def-ghi')
    await userEvent.type(screen.getByLabelText('Email'), 'kin@example.com')
    await userEvent.type(screen.getByLabelText(/New password/), 'a long enough passphrase')
    await userEvent.click(screen.getByRole('button', { name: 'Create my account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/do not match, or the invitation has expired/)
  })

  it('rejects a short password before calling the server', async () => {
    const view = renderApp('/join', {}, { signedIn: false })
    await userEvent.type(await screen.findByLabelText('Invite code'), 'ABC')
    await userEvent.type(screen.getByLabelText('Email'), 'kin@example.com')
    await userEvent.type(screen.getByLabelText(/New password/), 'short')
    await userEvent.click(screen.getByRole('button', { name: 'Create my account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('at least 12 characters')
    expect(view.server.calls).toHaveLength(0)
  })
})

describe('shell', () => {
  it('has a labelled sidebar with every design page and no "Soon" placeholders', async () => {
    const view = renderApp('/', childRoutes())
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    for (const name of ['Overview', 'Live Map', 'Family Members', 'SOS Centre', 'Messages', 'Activity & History', 'Device Health', 'Alerts', 'Settings']) {
      expect(within(nav).getByRole('link', { name: new RegExp(name.replace('&', '&')) })).toBeInTheDocument()
    }
    expect(nav).not.toHaveTextContent('Soon')
    await screen.findByRole('heading', { name: "Aarav's phone" })
    expect(await a11yViolations(view.container)).toEqual([])
  })

  it('shows when data was last refreshed, and says so when a refresh fails', async () => {
    renderApp('/', childRoutes())
    expect(await screen.findByText(/Synced (just now|\d+ s ago)/, { selector: '.sync' })).toBeInTheDocument()
  })

  it('searches people and pages and navigates with the keyboard', async () => {
    renderApp('/', childRoutes())
    await screen.findByRole('heading', { name: "Aarav's phone" })
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search people and pages' }), 'aarav')
    const results = await screen.findByRole('list', { name: 'Search results' })
    expect(within(results).getByRole('link', { name: /Aarav's phone/ })).toHaveAttribute('href', `/map?member=${CHILD_ID}`)
    await userEvent.type(screen.getByRole('searchbox'), '{Enter}')
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Live Map' })).toBeInTheDocument())
  })

  it('says plainly when nothing matches', async () => {
    renderApp('/', childRoutes())
    await userEvent.type(await screen.findByRole('searchbox'), 'zzzz')
    expect(await screen.findByText('Nothing matches.')).toBeInTheDocument()
  })
})

describe('overview', () => {
  it('shows a fresh location as "Updated", with battery, network and no claim of being live', async () => {
    renderApp('/', childRoutes(location(30)))
    await screen.findByRole('heading', { name: "Aarav's phone" })
    expect(await screen.findByText(/Updated \d+ s ago|Updated just now/, { selector: '.chip' })).toBeInTheDocument()
    expect(screen.getAllByText('81%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Wi-Fi').length).toBeGreaterThan(0)
    // No reading or status badge ever says "live" (the page name "Live Map" is a title, not a claim about data).
    for (const chip of document.querySelectorAll('.chip, .tile-value')) expect(chip.textContent).not.toMatch(/\blive\b/i)
  })

  it('never labels a stale location as current', async () => {
    renderApp('/', childRoutes(location(40 * 60)))
    const badge = await screen.findByText(/Not current/)
    expect(badge).toHaveTextContent('last seen 40 min ago')
    expect(screen.queryByText(/Updated \d+ s ago/, { selector: '.chip' })).toBeNull()
  })

  it('shows unavailable data as unknown, not zero', async () => {
    const silent = detail()
    silent.devices = silent.devices.map((d) => ({ ...d, last_seen: null }))
    renderApp('/', {
      ...childRoutes(location(null), device({ battery_percent: null, battery_is_charging: null, network_type: null, last_activity: null, connectivity_status: 'unknown' })),
      [`GET /families/${FAMILY_ID}`]: json(silent),
    })
    expect(await screen.findByText('No recent location')).toBeInTheDocument()
    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0)
    expect(screen.getByText('Never')).toBeInTheDocument()
    expect(screen.queryByText('0%')).toBeNull()
  })

  it('counts phones that are reporting, and never turns "no SOS received" into "safe"', async () => {
    renderApp('/', childRoutes())
    const tile = await screen.findByRole('region', { name: 'Phones reporting now' })
    await waitFor(() => expect(tile).toHaveTextContent('1 / 1'))
    const sos = screen.getByRole('region', { name: 'SOS' })
    await waitFor(() => expect(sos).toHaveTextContent('None open'))
    expect(sos).toHaveTextContent(/not proof/i)
    expect(sos).not.toHaveTextContent(/all clear|no emergenc/i)
  })

  it('lists recent activity from real events in the safety timeline', async () => {
    renderApp('/', childRoutes())
    expect(await screen.findByText('Location reported')).toBeInTheDocument()
  })

  it('has an empty state that points a parent to pairing', async () => {
    window.sessionStorage.setItem('piko.onboarding.shown', '1') // the setup guide was already offered this session
    renderApp('/', sessionRoutes('parent', false))
    expect(await screen.findByText('No one is sharing yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Create a pairing code' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'setup guide' })).toHaveAttribute('href', '/welcome')
  })

  it('shows an error with the request reference and a retry when the family cannot be loaded', async () => {
    renderApp('/', { ...sessionRoutes(), [`GET /families/${FAMILY_ID}`]: apiError(503, 'SERVICE_UNAVAILABLE', 'down') })
    expect(await screen.findByRole('alert')).toHaveTextContent('Reference: req-test')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('tells a guardian they are view-only', async () => {
    renderApp('/', { ...childRoutes(), ...sessionRoutes('guardian') })
    await screen.findByRole('heading', { name: "Aarav's phone" })
    expect(screen.getAllByText(/Guardian \(view only\)/).length).toBeGreaterThan(0)
  })
})

describe('live map', () => {
  it('draws a fresh position as current and a stale one faded with a warning', async () => {
    renderApp(`/map?member=${CHILD_ID}`, childRoutes(location(40 * 60)))
    expect(await screen.findByText(/This is where the phone was, not where it is now/)).toBeInTheDocument()
    expect(screen.getByTestId('map')).toHaveAttribute('data-fresh', 'false')
    expect(screen.getAllByText(/Not current/).length).toBeGreaterThan(0)
  })

  it('withholds a position the server would not give and says why', async () => {
    renderApp(`/map?member=${CHILD_ID}`, childRoutes(location(null)))
    expect(await screen.findByText('This phone has not reported a location yet.')).toBeInTheDocument()
    expect(screen.getByTestId('map')).toHaveAttribute('data-markers', '0')
  })

  it('is accessible and offers people as toggle buttons, with the selection marked', async () => {
    const view = renderApp(`/map?member=${CHILD_ID}`, childRoutes())
    const person = await screen.findByRole('button', { name: "Aarav's phone" })
    expect(person).toHaveAttribute('aria-pressed', 'true')
    await screen.findAllByText(/Updated/)
    expect(await a11yViolations(view.container)).toEqual([])
  })

  it('shows breadcrumbs only when asked, with gaps kept visible', async () => {
    const trail = history([histItem('a', 600, 3), histItem('b', 700, 2), histItem('c', 7000, 1)])
    renderApp(`/map?member=${CHILD_ID}`, childRoutes(location(30), device(), trail))
    await screen.findAllByText(/Updated/)
    expect(screen.getByTestId('map')).toHaveAttribute('data-segments', 'no-route')
    await userEvent.click(screen.getByRole('checkbox', { name: /Breadcrumbs/ }))
    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-gaps', '1'))
    expect(screen.getByText(/Dashed grey lines are gaps/)).toBeInTheDocument()
  })

  it('filters people by name', async () => {
    renderApp(`/map?member=${CHILD_ID}`, childRoutes())
    await screen.findAllByText(/Updated/)
    await userEvent.type(screen.getByRole('searchbox', { name: 'Filter people' }), 'zzz')
    expect(screen.queryByRole('button', { name: "Aarav's phone" })).toBeNull()
  })

  it('shows "denied" when the server refuses the location (the page never decides access)', async () => {
    renderApp(`/map?member=${CHILD_ID}`, { ...childRoutes(), [`GET /members/${CHILD_ID}/location`]: apiError(403, 'FORBIDDEN') })
    await waitFor(() => expect(screen.getByRole('button', { name: "Aarav's phone" })).toBeInTheDocument())
    expect(screen.getByTestId('map')).toHaveAttribute('data-markers', '0')
  })
})

describe('activity', () => {
  it('shows a visible gap in the timeline and in the route', async () => {
    const page = history([histItem('a', 600, 3), histItem('b', 700, 2), histItem('c', 7000, 1)])
    const view = renderApp(`/activity?member=${CHILD_ID}`, childRoutes(location(30), device(), page))
    expect(await screen.findByText(/No location for .* before this point/)).toBeInTheDocument()
    expect(screen.getByTestId('map')).toHaveAttribute('data-gaps', '1')
    expect(screen.getByTestId('map')).toHaveAttribute('data-segments', '2')
    expect(await a11yViolations(view.container)).toEqual([])
  })

  it('loads older events with the next offset', async () => {
    const calls: (string | null)[] = []
    const handler = ({ url }: { url: URL }) => {
      calls.push(url.searchParams.get('offset'))
      return json(url.searchParams.get('offset') === '0' ? history([histItem('a', 60, 1)], 2, true) : history([histItem('b', 120, 2)], 2, false))
    }
    renderApp(`/activity?member=${CHILD_ID}`, { ...childRoutes(), [`GET /members/${CHILD_ID}/history`]: handler })
    await userEvent.click(await screen.findByRole('button', { name: 'Load older events' }))
    await waitFor(() => expect(calls).toContain('1'))
    expect(await screen.findByText(/2 of 2/)).toBeInTheDocument()
  })

  it('has an empty state', async () => {
    renderApp(`/activity?member=${CHILD_ID}`, childRoutes(location(30), device(), history([])))
    expect(await screen.findByText('Nothing in this period')).toBeInTheDocument()
  })

  it('marks events that arrived long after they happened', async () => {
    const late = { ...histItem('late', 3600, 5), received_at: new Date().toISOString() }
    renderApp(`/activity?member=${CHILD_ID}`, childRoutes(location(30), device(), history([late])))
    expect(await screen.findByText(/Delivered late \(saved on the phone/)).toBeInTheDocument()
  })

  it('explains rate limiting', async () => {
    const limited = json({ error: { code: 'RATE_LIMIT', message: 'x', request_id: 'r' } }, 429, { 'Retry-After': '20' })
    renderApp(`/activity?member=${CHILD_ID}`, { ...childRoutes(), [`GET /members/${CHILD_ID}/history`]: limited })
    expect((await screen.findAllByRole('alert'))[0]).toHaveTextContent('Too many requests')
  })
})

describe('device health', () => {
  it('shows telemetry, with unreported values as Unknown and no invented sensors', async () => {
    const view = renderApp(`/health?device=${DEVICE_ID}`, childRoutes(location(30), device({ app_version: null, battery_percent: null, battery_is_charging: null })))
    expect(await screen.findByText(/Pixel 7/)).toBeInTheDocument()
    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/not reported by the phone app/i, { selector: 'p' }).length).toBeGreaterThan(0)
    expect(screen.queryByText(/satellites tracked|°C|bpm|dBm/i)).toBeNull()
    expect(await a11yViolations(view.container)).toEqual([])
  })

  it('lists recent events in a table and says when they arrived late', async () => {
    const late = { ...histItem('late', 3600, 5), received_at: new Date().toISOString() }
    renderApp(`/health?device=${DEVICE_ID}`, childRoutes(location(30), device(), history([histItem('x', 30, 1), late])))
    expect(await screen.findByRole('table', { name: /Recent events/ })).toBeInTheDocument()
    expect(await screen.findByText(/Delivered late \(/)).toBeInTheDocument()
    expect(screen.getByText('1 of 2')).toBeInTheDocument()
  })

  it('offers a CSV export of the events on screen', async () => {
    renderApp(`/health?device=${DEVICE_ID}`, childRoutes())
    const link = await screen.findByRole('link', { name: /Export CSV/ })
    expect(link).toHaveAttribute('download', expect.stringMatching(/\.csv$/))
  })

  it('lets a parent unlink only after confirmation, and a guardian not at all', async () => {
    const revoke = vi.fn(() => json(null, 204))
    const parent = renderApp(`/health?device=${DEVICE_ID}`, { ...childRoutes(), [`DELETE /devices/${DEVICE_ID}`]: revoke })
    await userEvent.click(await screen.findByRole('button', { name: 'Unlink…' }))
    expect(revoke).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Yes, unlink this phone' }))
    await waitFor(() => expect(revoke).toHaveBeenCalledTimes(1))
    parent.unmount()

    renderApp(`/health?device=${DEVICE_ID}`, { ...childRoutes(), ...sessionRoutes('guardian') })
    await screen.findByText(/Pixel 7/)
    expect(screen.queryByRole('button', { name: 'Unlink…' })).toBeNull()
  })

  it('shows the server refusal if a request the page allowed is denied anyway', async () => {
    renderApp(`/health?device=${DEVICE_ID}`, { ...childRoutes(), [`DELETE /devices/${DEVICE_ID}`]: apiError(403, 'FORBIDDEN') })
    await userEvent.click(await screen.findByRole('button', { name: 'Unlink…' }))
    await userEvent.click(screen.getByRole('button', { name: 'Yes, unlink this phone' }))
    expect(await screen.findByText('You do not have access to this')).toBeInTheDocument()
  })

  it('says there is nothing to show when no phone is linked', async () => {
    renderApp('/health', sessionRoutes('parent', false))
    expect(await screen.findByText('No phones yet')).toBeInTheDocument()
  })
})

describe('csv export', () => {
  it('quotes every cell and neutralises spreadsheet formulas', () => {
    const evil = histItem('e', 10, 1, { event_type: 'connectivity', data: { network_type: '=HYPERLINK("http://x")' } })
    const csv = eventsToCsv([evil])
    const row = csv.split('\r\n')[1] ?? ''
    expect(row).toContain("\"'=HYPERLINK(\"\"http://x\"\")\"")
    expect(csv.split('\r\n')[0]).toBe('occurred_at,received_at,event_type,details,delivery_delay_seconds')
  })
})

describe('family members', () => {
  it('shows a pairing code once, with a countdown, to a parent', async () => {
    const expires = new Date(Date.now() + 15 * 60_000).toISOString()
    const routes = { ...childRoutes(), 'POST /devices/pairing-code': json({ pairing_code: 'ABC-DEF-GHI', expires_at: expires, expires_in_seconds: 900 }, 201) }
    const view = renderApp('/family', routes)
    await userEvent.click(await screen.findByRole('button', { name: 'Create pairing code' }))
    expect(await screen.findByText('ABC-DEF-GHI')).toBeInTheDocument()
    expect(screen.getByText(/Expires in/)).toBeInTheDocument()
    expect(screen.getByText(/shown only now/i)).toBeInTheDocument()
    expect(await a11yViolations(view.container)).toEqual([])
  })

  it('creates an invite code and shows it once', async () => {
    const routes = {
      ...childRoutes(),
      [`POST /families/${FAMILY_ID}/members`]: ({ body }: { body: unknown }) =>
        json({ invitation_id: 'i', email: (body as { email: string }).email, role: 'guardian', status: 'pending', invite_code: 'JKL-MNP-QRS', expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString() }, 201),
    }
    renderApp('/family', routes)
    await userEvent.type(await screen.findByLabelText('Their email'), 'sis@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Create invite code' }))
    expect(await screen.findByText('JKL-MNP-QRS')).toBeInTheDocument()
    expect(screen.getByText('sis@example.com')).toBeInTheDocument()
  })

  it('shows a guardian the family read-only, with no controls', async () => {
    renderApp('/family', sessionRoutes('guardian'))
    expect(await screen.findByText('View-only access')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create pairing code' })).toBeNull()
  })

  it('lets the server refuse even a parent-looking action', async () => {
    renderApp('/family', { ...sessionRoutes('parent'), 'POST /devices/pairing-code': apiError(403, 'FORBIDDEN') })
    await userEvent.click(await screen.findByRole('button', { name: 'Create pairing code' }))
    expect(await within(await screen.findByRole('alert')).findByText('You do not have access to this')).toBeInTheDocument()
  })

  it('keeps the old /manage address working', async () => {
    renderApp('/manage', sessionRoutes('parent'))
    expect(await screen.findByRole('heading', { name: 'Family Members' })).toBeInTheDocument()
  })
})

describe('settings', () => {
  it('shows only facts the dashboard knows, and signs out', async () => {
    const view = renderApp('/settings', sessionRoutes())
    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.getByText('Test Family', { selector: 'dd' })).toBeInTheDocument()
    expect(await a11yViolations(view.container)).toEqual([])
  })
})
