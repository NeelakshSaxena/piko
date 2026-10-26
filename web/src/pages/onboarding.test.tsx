import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { a11yViolations, json, renderApp, sessionRoutes } from '../test/helpers'

// Leaflet needs real layout; the overview's map is exercised in the browser, not in jsdom.
vi.mock('../components/Map', () => ({
  FleetMap: () => <div role="img" aria-label="map" />,
  TileNotice: () => <p>tile notice</p>,
}))

beforeEach(() => window.sessionStorage.clear())

describe('parent onboarding', () => {
  it('sends a parent with no linked phone to the setup guide once, then lets them reach the dashboard', async () => {
    renderApp('/', sessionRoutes('parent', false))
    expect(await screen.findByRole('heading', { name: 'Welcome to Piko' })).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('link', { name: /Skip for now/ }))
    expect(await screen.findByText('No one is sharing yet')).toBeInTheDocument()
  })

  it('is accessible, explains what is shared and shows the child-consent and not-an-emergency-service wording', async () => {
    const view = renderApp('/welcome', sessionRoutes('parent', false))
    expect(await screen.findByText(/the child has to agree on the phone/i)).toBeInTheDocument()
    expect(screen.getByText(/not an emergency service/i, { selector: 'li' })).toBeInTheDocument()
    expect(await a11yViolations(view.container)).toEqual([])
  })

  it('shows a pairing code only after the server issues it and marks the phone step done only when the family shows a phone', async () => {
    renderApp(
      '/welcome',
      {
        ...sessionRoutes('parent', false),
        'POST /devices/pairing-code': json({ pairing_code: 'K7M2QX9P', expires_at: new Date(Date.now() + 600_000).toISOString() }, 201),
      },
    )
    await screen.findByRole('heading', { name: /Step 2: Link a child's phone/ })
    expect(screen.getByText('To do')).toBeInTheDocument()
    expect(screen.queryByText('K7M2QX9P')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create pairing code' }))
    expect(await screen.findByText('K7M2QX9P')).toBeInTheDocument()
    expect(screen.queryByText('Done')).not.toBeInTheDocument()
  })

  it('marks the phone step done when a phone is linked', async () => {
    renderApp('/welcome', sessionRoutes('parent', true))
    expect(await screen.findByText('Done')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to the dashboard' })).toHaveAttribute('href', '/')
  })

  it('does not force the guide on a parent who already has a phone linked', async () => {
    renderApp('/', { ...sessionRoutes('parent', true), 'GET /members/member-child/location': json({}) })
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Welcome to Piko' })).not.toBeInTheDocument())
  })

  it('keeps a view-only guardian out of the guide', async () => {
    renderApp('/welcome', sessionRoutes('guardian', false))
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Welcome to Piko' })).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Create pairing code' })).not.toBeInTheDocument()
  })
})
