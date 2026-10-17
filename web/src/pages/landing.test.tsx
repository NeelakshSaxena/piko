import { render, screen } from '@testing-library/react'
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

    // Accessibility check
    expect(await a11yViolations(container)).toEqual([])
  })
})
