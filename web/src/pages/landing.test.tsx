import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { LandingPage } from './LandingPage'
import { a11yViolations } from '../test/helpers'

describe('LandingPage', () => {
  it('renders landing page with mascot, headlines, and ₹300 pricing', async () => {
    const { container } = render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { level: 1, name: /A little more peace of mind/i })).toBeInTheDocument()
    expect(screen.getByAltText(/Piko official friendly mascot/i)).toBeInTheDocument()

    // Hosted tier pricing check
    expect(screen.getByText('₹300')).toBeInTheDocument()
    expect(screen.getByText('/ family / month')).toBeInTheDocument()

    // Get started buttons link to /login
    const getStartedLinks = screen.getAllByRole('link', { name: /Get started/i })
    expect(getStartedLinks.length).toBeGreaterThan(0)
    for (const link of getStartedLinks) {
      expect(link).toHaveAttribute('href', '/login')
    }

    // Self-hosting tab: a nav link and a section with the real commands
    expect(screen.getAllByRole('link', { name: 'Deploy yourself' })[0]).toHaveAttribute('href', '#self-host')
    expect(screen.getByRole('heading', { level: 2, name: 'How to deploy Piko yourself' })).toBeInTheDocument()
    expect(screen.getByText(/python -m app.cli doctor/)).toBeInTheDocument()
    expect(screen.getByText(/python -m app.cli backup/)).toBeInTheDocument()

    // Accessibility check
    expect(await a11yViolations(container)).toEqual([])
  }, 30_000) // axe over the whole long page is slow on a busy machine

  it('applies the early-bird coupon without claiming anything was activated, and rejects other codes', async () => {
    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    )
    const input = screen.getByLabelText('Have a coupon code?')
    await userEvent.type(input, 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(screen.getByRole('status')).toHaveTextContent('not valid')
    await userEvent.clear(input)
    await userEvent.type(input, ' earlybirdoff3r ')
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(screen.getByRole('status')).toHaveTextContent(/first month of Piko Hosted is free/)
    expect(screen.getByRole('status')).toHaveTextContent(/nothing is charged or activated today/)
  })
})
