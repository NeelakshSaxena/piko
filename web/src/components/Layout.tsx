import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useFamily } from '../auth/FamilyContext'
import { useFleet } from '../auth/FleetContext'
import { useSos } from '../auth/SosContext'
import { ageSeconds, formatAge } from '../lib/format'
import { useNow } from '../lib/useAsync'
import { Icon, type IconName } from './Icon'
import { Avatar, OfflineBanner } from './ui'

interface NavItem {
  to: string
  label: string
  icon: IconName
}

export const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: 'overview' },
  { to: '/map', label: 'Live Map', icon: 'map' },
  { to: '/family', label: 'Family Members', icon: 'people' },
  { to: '/sos', label: 'SOS Centre', icon: 'sos' },
  { to: '/messages', label: 'Messages', icon: 'message' },
  { to: '/activity', label: 'Activity & History', icon: 'activity' },
  { to: '/health', label: 'Device Health', icon: 'device' },
  { to: '/alerts', label: 'Alerts', icon: 'bell' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
]

const ROLE_LABEL: Record<string, string> = {
  parent: 'Parent',
  family_admin: 'Family admin',
  guardian: 'Guardian (view only)',
  child: 'Child',
}

function SyncChip() {
  const { lastLoadedAt, failing, loading, entries } = useFleet()
  const now = useNow(5000)
  if (loading && lastLoadedAt === null) return <span className="sync sync-grey">Loading…</span>
  if (entries.length === 0) return <span className="sync sync-grey">No phones linked</span>
  const age = formatAge(ageSeconds(lastLoadedAt ? new Date(lastLoadedAt).toISOString() : null, now))
  if (failing) return <span className="sync sync-amber" role="status">Could not refresh · last update {age}</span>
  return (
    <span className="sync sync-mint" role="status">
      <Icon name="refresh" size={16} /> Synced {age}
    </span>
  )
}

/** Finds people and pages. Results are links, so it works with a keyboard and a screen reader. */
function SearchBox() {
  const { children } = useFamily()
  const { family } = useFamily()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        input.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    const people = children.map(({ member }) => ({ label: member.name ?? 'Unnamed phone', hint: 'Show on map', to: `/map?member=${member.id}` }))
    const adults = (family.data?.members ?? [])
      .filter((m) => m.role !== 'child')
      .map((m) => ({ label: m.name ?? m.email ?? 'Adult', hint: 'Family members', to: '/family' }))
    const pages = NAV.map((n) => ({ label: n.label, hint: 'Page', to: n.to }))
    return [...people, ...adults, ...pages].filter((r) => r.label.toLowerCase().includes(q)).slice(0, 6)
  }, [query, children, family.data])

  return (
    <form
      role="search"
      className="search"
      onSubmit={(e) => {
        e.preventDefault()
        const first = results[0]
        if (first) {
          navigate(first.to)
          setQuery('')
        }
      }}
    >
      <Icon name="search" size={18} />
      <input
        ref={input}
        type="search"
        aria-label="Search people and pages"
        placeholder="Search people, pages"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && setQuery('')}
      />
      <kbd aria-hidden="true">Ctrl K</kbd>
      {query.trim() && (
        <ul className="search-results" aria-label="Search results">
          {results.length === 0 && <li className="muted small">Nothing matches.</li>}
          {results.map((r) => (
            <li key={r.label + r.to}>
              <Link to={r.to} onClick={() => setQuery('')}>
                {r.label} <span className="muted small">· {r.hint}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </form>
  )
}

/** Always visible when an SOS is waiting, and also when the check itself is failing (never silently "none"). */
function SosBanner() {
  const { state, openCount } = useSos()
  if (openCount !== null && openCount > 0) {
    return (
      <div className="sos-banner" role="alert" key={openCount}>
        <strong>
          {openCount} SOS {openCount === 1 ? 'alert is' : 'alerts are'} open and not yet acknowledged.
        </strong>{' '}
        <Link to="/sos">Open the SOS Centre</Link>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <div className="banner" role="status">
        Piko could not check for SOS alerts{state.data ? ' just now; the last check may be out of date' : ''}. Do not assume there are none.
      </div>
    )
  }
  return null
}

export function Layout() {
  const { state, signOut } = useAuth()
  const { openCount } = useSos()
  const { family, children } = useFamily()
  const location = useLocation()
  if (state.status !== 'authenticated') return null
  const current = NAV.find((n) => (n.to === '/' ? location.pathname === '/' : location.pathname.startsWith(n.to)))
  const familyName = family.data?.name ?? state.family.name
  const phones = children.reduce((n, c) => n + c.devices.length, 0)

  return (
    <div className="shell">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="side">
        <div className="brand">
          <img src="/icon-192.png" alt="" width="40" height="40" />
          <div>
            <strong>Piko</strong>
            <span className="muted small">Family safety</span>
          </div>
        </div>
        <div className="family-card">
          <Avatar name={familyName} tone="mint" />
          <div>
            <strong>{familyName}</strong>
            <span className="muted small">
              {phones} phone{phones === 1 ? '' : 's'} linked
            </span>
          </div>
        </div>
        <nav aria-label="Main">
          <ul className="nav">
            {NAV.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.to === '/'} className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                  {item.to === '/sos' && openCount !== null && openCount > 0 && (
                    <span className="soon soon-alert">
                      {openCount}
                      <span className="sr-only"> open SOS</span>
                    </span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="user-card">
          <div>
            <strong>{ROLE_LABEL[state.role] ?? state.role}</strong>
            <span className="muted small">Signed in</span>
          </div>
          <button type="button" className="btn btn-soft" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </aside>

      <div className="content">
        <header className="top">
          <div className="crumbs" aria-label="Breadcrumb">
            <span className="muted">{familyName}</span>
            <span aria-hidden="true">›</span>
            <strong>{current?.label ?? 'Piko'}</strong>
          </div>
          <SyncChip />
          <SearchBox />
          <span className="chip chip-lavender role-chip">{ROLE_LABEL[state.role] ?? state.role}</span>
        </header>
        <OfflineBanner />
        <SosBanner />
        <main id="main" className="page">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
