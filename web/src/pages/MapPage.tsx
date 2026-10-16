import { useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useFleet } from '../auth/FleetContext'
import { Icon } from '../components/Icon'
import { FleetMap, TileNotice, type MapHandle } from '../components/Map'
import { Avatar, Card, Chip, Empty, ErrorState, FreshnessBadge, Loading, PageTitle, StatusBadge } from '../components/ui'
import { accuracyText, ageSeconds, batteryText, chargingText, coordinateText, formatAge, formatDateTime, freshnessOf, networkText } from '../lib/format'
import { buildRoute, locationPoints } from '../lib/route'
import { config } from '../config'
import { useAsync, useNow } from '../lib/useAsync'
import { markersOf } from './OverviewPage'

const TRAIL_HOURS = 4

export function MapPage() {
  const { api } = useAuth()
  const { entries, loading, reload } = useFleet()
  const [params, setParams] = useSearchParams()
  const now = useNow(10_000)
  const mapRef = useRef<MapHandle>(null)
  const [query, setQuery] = useState('')
  const [trail, setTrail] = useState(false)

  const visible = entries.filter((e) => (e.member.name ?? '').toLowerCase().includes(query.trim().toLowerCase()))
  const selected = entries.find((e) => e.member.id === params.get('member')) ?? (params.get('member') === 'all' ? undefined : entries[0])
  const markers = useMemo(() => markersOf(visible, now), [visible, now])

  // Breadcrumbs are read on demand (each read is recorded in the audit log), only while the toggle is on.
  const history = useAsync(
    async () => {
      if (!trail || !selected) return null
      return api.memberHistory(selected.member.id, {
        limit: 200,
        event_type: 'location',
        start_time: new Date(Date.now() - TRAIL_HOURS * 3600_000).toISOString(),
      })
    },
    [api, trail, selected?.member.id],
  )
  const route = useMemo(() => (trail && history.state.data ? buildRoute(locationPoints(history.state.data.history), config.gapSeconds) : null), [trail, history.state.data])

  const loc = selected?.location
  const freshness = loc?.available ? freshnessOf(loc.occurred_at, now) : 'unknown'
  const age = ageSeconds(loc?.occurred_at, now)
  const coords = loc?.available && loc.coordinates ? loc.coordinates : null

  return (
    <>
      <PageTitle>Live Map</PageTitle>
      {loading && entries.length === 0 && <Loading label="Loading phones…" />}
      {!loading && entries.length === 0 && <Empty title="No one to show">Once a child's phone is linked and sharing, its position appears here.</Empty>}

      {entries.length > 0 && (
        <div className="map-layout">
          <div className="stack">
            <Card>
              <div className="row between">
                <div className="chips" role="group" aria-label="Choose a person">
                  <button type="button" className={`pill ${!selected ? 'on' : ''}`} aria-pressed={!selected} onClick={() => { setParams({ member: 'all' }); mapRef.current?.fitAll() }}>
                    All ({entries.length})
                  </button>
                  {visible.map(({ member }) => (
                    <button
                      key={member.id}
                      type="button"
                      className={`pill ${selected?.member.id === member.id ? 'on' : ''}`}
                      aria-pressed={selected?.member.id === member.id}
                      onClick={() => setParams({ member: member.id })}
                    >
                      {member.name ?? 'Unnamed phone'}
                    </button>
                  ))}
                </div>
                <label className="inline-search">
                  <span className="sr-only">Filter people</span>
                  <input type="search" placeholder="Filter people" value={query} onChange={(e) => setQuery(e.target.value)} />
                </label>
              </div>
              <div className="row">
                <label className="toggle">
                  <input type="checkbox" checked={trail} onChange={(e) => setTrail(e.target.checked)} disabled={!selected} />
                  <span>Breadcrumbs (last {TRAIL_HOURS} h)</span>
                </label>
                <button type="button" className="btn btn-soft" onClick={() => mapRef.current?.fitAll()}>
                  Fit all
                </button>
                {selected && coords && (
                  <button type="button" className="btn btn-soft" onClick={() => mapRef.current?.focus(selected.member.id)}>
                    Recenter on {selected.member.name ?? 'phone'}
                  </button>
                )}
                <button type="button" className="btn btn-soft" onClick={() => void reload()}>
                  <Icon name="refresh" size={16} /> Refresh
                </button>
              </div>
              {trail && history.state.status === 'loading' && <p className="muted small">Loading breadcrumbs…</p>}
              {trail && history.state.status === 'error' && <ErrorState error={history.state.error} what="the breadcrumbs" onRetry={() => void history.reload()} />}
              {trail && history.state.data && route && route.segments.length === 0 && <p className="muted small">No locations were reported in the last {TRAIL_HOURS} hours.</p>}
              {trail && route && route.gaps.length > 0 && (
                <p className="muted small">Dashed grey lines are gaps longer than {Math.round(config.gapSeconds / 60)} minutes: the real path there is unknown.</p>
              )}
            </Card>
            <FleetMap
              ref={mapRef}
              markers={markers}
              selectedId={selected?.member.id}
              route={route && route.segments.length > 0 ? route : null}
              label="Live map"
              height={480}
              autoFit={selected ? 'selected' : 'all'}
              onSelect={(id) => setParams({ member: id })}
            />
            <TileNotice />
          </div>

          <aside className="stack" aria-label="Selected person">
            {selected ? (
              <>
                <Card>
                  <div className="row between">
                    <div className="row">
                      <Avatar name={selected.member.name ?? '?'} />
                      <h2 className="h2 flush">{selected.member.name ?? 'Unnamed phone'}</h2>
                    </div>
                    {loc && <StatusBadge status={loc.device_status} />}
                  </div>
                  {selected.error && (
                    <p className="muted small" role="status">
                      Could not refresh just now. Showing what was last loaded.
                    </p>
                  )}
                  <p aria-live="polite">
                    <FreshnessBadge freshness={freshness} ageSeconds={age} />{' '}
                    {coords && <span className="muted small">{accuracyText(loc?.accuracy_meters)}</span>}
                  </p>
                  {freshness === 'stale' && coords && (
                    <p className="warn" role="note">
                      This is where the phone was, not where it is now.
                    </p>
                  )}
                  {loc && !coords && (
                    <p className="muted">
                      {loc.occurred_at ? `The last location was taken ${formatDateTime(loc.occurred_at)}, which is too old to show as a position.` : 'This phone has not reported a location yet.'}
                    </p>
                  )}
                  {coords && (
                    <p className="muted small">
                      {coordinateText(coords.latitude, coords.longitude)} · taken {formatDateTime(loc?.occurred_at)}
                    </p>
                  )}
                </Card>
                <div className="tiles two">
                  <Card>
                    <div className="tile-label">Battery</div>
                    <div className="tile-value">{batteryText(selected.detail?.battery_percent)}</div>
                    <div className="muted small">{chargingText(selected.detail?.battery_is_charging)}</div>
                  </Card>
                  <Card>
                    <div className="tile-label">Network</div>
                    <div className="tile-value small-value">{networkText(selected.detail?.network_type)}</div>
                    <div className="muted small">
                      {selected.detail?.network_updated_at ? `reported ${formatAge(ageSeconds(selected.detail.network_updated_at, now))}` : 'never reported'}
                    </div>
                  </Card>
                </div>
                <Card>
                  <div className="row">
                    <Link className="btn btn-soft" to={`/health?device=${selected.device?.id ?? ''}`}>
                      Device health
                    </Link>
                    <Link className="btn btn-soft" to={`/activity?member=${selected.member.id}`}>
                      Activity
                    </Link>
                  </div>
                </Card>
              </>
            ) : (
              <Card>
                <h2 className="h2">Everyone</h2>
                <ul className="plain">
                  {entries.map((e) => (
                    <li key={e.member.id} className="row between">
                      <span>{e.member.name ?? 'Unnamed phone'}</span>
                      {e.location ? <StatusBadge status={e.location.device_status} /> : <Chip tone="grey">Checking…</Chip>}
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </aside>
        </div>
      )}
    </>
  )
}
