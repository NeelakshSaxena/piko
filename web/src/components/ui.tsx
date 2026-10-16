import { useEffect, useRef, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { DeviceStatus, Freshness } from '../api/types'
import { deviceStatusText, formatAge } from '../lib/format'
import { useOnline } from '../lib/useAsync'

export function Card({ children, tone, className = '' }: { children: ReactNode; tone?: 'mint' | 'sky' | 'peach' | 'rose'; className?: string }) {
  return <section className={`card ${tone ? `card-${tone}` : ''} ${className}`}>{children}</section>
}

export function Chip({ children, tone = 'lavender' }: { children: ReactNode; tone?: 'lavender' | 'mint' | 'amber' | 'sky' | 'grey' | 'rose' }) {
  return <span className={`chip chip-${tone}`}>{children}</span>
}

/**
 * The only place a location's currency is worded. "Live" is deliberately not a state: the best a
 * reading can be is "Updated a moment ago", and anything older than five minutes says so.
 */
export function FreshnessBadge({ freshness, ageSeconds }: { freshness: Freshness; ageSeconds: number | null }) {
  if (freshness === 'fresh') return <Chip tone="mint">Updated {formatAge(ageSeconds)}</Chip>
  if (freshness === 'stale') return <Chip tone="amber">Not current · last seen {formatAge(ageSeconds)}</Chip>
  return <Chip tone="grey">No recent location</Chip>
}

export function StatusBadge({ status }: { status: DeviceStatus }) {
  const tone = status === 'online' ? 'mint' : status === 'offline' ? 'amber' : 'grey'
  return <Chip tone={tone}>{deviceStatusText(status)}</Chip>
}

/** Initials in a coloured disc. Piko holds no photos, so there is never a stand-in face. */
export function Avatar({ name, tone = 'lavender', size = 44 }: { name: string; tone?: 'lavender' | 'mint' | 'peach' | 'sky'; size?: number }) {
  const initials = name
    .split(/[\s_]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
  return (
    <span className={`avatar avatar-${tone}`} style={{ width: size, height: size }} aria-hidden="true">
      {initials || '?'}
    </span>
  )
}

/** A headline number or word with a caption. `unknown` is rendered as Unknown, never as zero. */
export function Tile({ icon, label, value, note, tone }: { icon: ReactNode; label: string; value: ReactNode; note?: ReactNode; tone?: 'mint' | 'sky' | 'peach' | 'rose' | 'lavender' }) {
  return (
    <section className="tile" aria-label={label}>
      <span className={`tile-icon tone-${tone ?? 'lavender'}`}>{icon}</span>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {note && <div className="tile-note muted small">{note}</div>}
    </section>
  )
}

/** A page for a product area that does not exist yet. It says so plainly and shows nothing simulated. */
export function NotAvailable({ title, intro, children }: { title: string; intro: string; children?: ReactNode }) {
  return (
    <>
      <PageTitle>{title}</PageTitle>
      <Card tone="sky">
        <h2 className="h2">Not available in this version</h2>
        <p>{intro}</p>
        {children}
      </Card>
    </>
  )
}

export function PageTitle({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    ref.current?.focus() // moves keyboard and screen-reader focus to the new page's heading
  }, [])
  return (
    <h1 ref={ref} tabIndex={-1} className="page-title">
      {children}
    </h1>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <Card>
      <h2 className="h2">{title}</h2>
      {children && <div className="muted">{children}</div>}
    </Card>
  )
}

/** Turns an API failure into a plain explanation. 401 never reaches here: it ends the session instead. */
export function ErrorState({ error, onRetry, what = 'this' }: { error: ApiError; onRetry?: () => void; what?: string }) {
  let title = `Could not load ${what}`
  let body = error.message
  if (error.code === 'NETWORK') {
    title = 'Cannot reach the Piko server'
    body = 'Check your connection. What you see below, if anything, is the last information that was loaded and may be out of date.'
  } else if (error.denied) {
    title = 'You do not have access to this'
    body = 'Your role in this family does not allow it. The server decides this, not the page.'
  } else if (error.status === 404) {
    title = 'Not found'
    body = 'It does not exist, or it is not part of your family.'
  } else if (error.code === 'RATE_LIMIT') {
    title = 'Too many requests'
    body = `Please wait${error.retryAfterSeconds ? ` ${error.retryAfterSeconds} seconds` : ' a moment'} and try again.`
  }
  return (
    <div className="card card-rose" role="alert">
      <h2 className="h2">{title}</h2>
      <p>{body}</p>
      {error.requestId && <p className="muted small">Reference: {error.requestId}</p>}
      {onRetry && (
        <button type="button" className="btn btn-soft" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function OfflineBanner() {
  const online = useOnline()
  if (online) return null
  return (
    <div className="banner" role="status">
      This device is offline. Values on screen may be out of date.
    </div>
  )
}
