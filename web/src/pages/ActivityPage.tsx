import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { HistoryItem } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useFamily } from '../auth/FamilyContext'
import { Card, Chip, Empty, ErrorState, Loading, PageTitle } from '../components/ui'
import { FleetMap, TileNotice } from '../components/Map'
import { config } from '../config'
import { accuracyText, batteryText, formatDateTime, formatDuration } from '../lib/format'
import { buildRoute, locationPoints } from '../lib/route'

const WINDOWS = [
  { id: '1h', label: 'Last hour', seconds: 3600 },
  { id: '24h', label: 'Last 24 hours', seconds: 86_400 },
  { id: '7d', label: 'Last 7 days', seconds: 7 * 86_400 },
  { id: '30d', label: 'Last 30 days', seconds: 30 * 86_400 },
] as const
const PAGE = 100

function describe(item: HistoryItem): string {
  const d = item.data
  if (item.event_type === 'location' && typeof d.latitude === 'number' && typeof d.longitude === 'number') {
    const acc = typeof d.accuracy_meters === 'number' ? accuracyText(d.accuracy_meters) : 'accuracy unknown'
    return `Location ${d.latitude.toFixed(5)}, ${d.longitude.toFixed(5)} (${acc})`
  }
  if (item.event_type === 'battery') {
    const charging = d.is_charging === true ? ', charging' : d.is_charging === false ? ', not charging' : ''
    return `Battery ${batteryText(typeof d.percent === 'number' ? d.percent : null)}${charging}`
  }
  if (item.event_type === 'connectivity') return `Network: ${typeof d.network_type === 'string' ? d.network_type : 'unknown'}`
  return item.event_type
}

export function ActivityPage() {
  const { api } = useAuth()
  const { children, family } = useFamily()
  const [params, setParams] = useSearchParams()
  const selected = children.find((c) => c.member.id === params.get('member')) ?? children[0]
  const memberId = selected?.member.id
  const [windowId, setWindowId] = useState<(typeof WINDOWS)[number]['id']>('24h')
  const [type, setType] = useState<'all' | 'location' | 'battery' | 'connectivity'>('all')
  const [items, setItems] = useState<HistoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [more, setMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const load = useCallback(
    async (offset: number) => {
      if (!memberId) return
      const seconds = WINDOWS.find((w) => w.id === windowId)?.seconds ?? 86_400
      setLoading(true)
      setError(null)
      try {
        const page = await api.memberHistory(memberId, {
          limit: PAGE,
          offset,
          start_time: new Date(Date.now() - seconds * 1000).toISOString(),
          event_type: type === 'all' ? undefined : type,
        })
        setItems((prev) => (offset === 0 ? page.history : [...prev, ...page.history]))
        setTotal(page.total_count)
        setMore(page.has_more)
      } catch (e) {
        setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', 'Something went wrong.'))
      } finally {
        setLoading(false)
      }
    },
    [api, memberId, windowId, type],
  )

  // History is read on demand, not polled: each read is recorded in the family's audit log.
  useEffect(() => {
    setItems([])
    void load(0)
  }, [load])

  const route = useMemo(() => buildRoute(locationPoints(items), config.gapSeconds), [items])
  const gapAfter = useMemo(() => {
    // Newest-first list: map each event to the quiet period that precedes it in time, if any.
    const gaps = new Map<string, number>()
    const locations = items.filter((i) => i.event_type === 'location')
    locations.forEach((current, index) => {
      const older = locations[index + 1]
      if (!older) return
      const seconds = (Date.parse(current.occurred_at) - Date.parse(older.occurred_at)) / 1000
      if (seconds > config.gapSeconds) gaps.set(current.event_id, Math.round(seconds))
    })
    return gaps
  }, [items])

  return (
    <>
      <PageTitle>Activity</PageTitle>
      {family.status === 'loading' && !family.data && <Loading />}
      {family.data && children.length === 0 && <Empty title="No activity yet">History appears after a child's phone is linked and has shared.</Empty>}
      {selected && (
        <>
          <Card>
            <div className="filters">
              <label>
                Person
                <select value={memberId} onChange={(e) => setParams({ member: e.target.value })}>
                  {children.map(({ member }) => (
                    <option key={member.id} value={member.id}>
                      {member.name ?? 'Unnamed phone'}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Time
                <select value={windowId} onChange={(e) => setWindowId(e.target.value as typeof windowId)}>
                  {WINDOWS.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Show
                <select value={type} onChange={(e) => setType(e.target.value as typeof type)}>
                  <option value="all">Everything</option>
                  <option value="location">Locations</option>
                  <option value="battery">Battery</option>
                  <option value="connectivity">Network</option>
                </select>
              </label>
              <button type="button" className="btn btn-soft" onClick={() => void load(0)} disabled={loading}>
                Refresh
              </button>
            </div>
          </Card>

          {error && <ErrorState error={error} what="the history" onRetry={() => void load(0)} />}
          {loading && items.length === 0 && <Loading label="Loading history…" />}

          {!loading && !error && items.length === 0 && <Empty title="Nothing in this period">The phone has not reported anything in this time range.</Empty>}

          {items.length > 0 && (
            <>
              {route.segments.length > 0 && (
                <section aria-labelledby="route-h">
                  <h2 id="route-h" className="h2">
                    Route
                  </h2>
                  <FleetMap markers={[]} route={route} label={`Route for ${selected.member.name ?? 'this person'}`} height={380} />
                  <p className="muted small">
                    Solid lines are movement that was reported. Dashed grey lines mean the phone sent no location for more than{' '}
                    {formatDuration(config.gapSeconds)}; the real path in between is unknown.
                  </p>
                  <TileNotice />
                </section>
              )}
              <section aria-labelledby="events-h">
                <h2 id="events-h" className="h2">
                  Events{' '}
                  <span className="muted small">
                    ({items.length} of {total}, newest first)
                  </span>
                </h2>
                <Card>
                  <ol className="timeline">
                    {items.map((item) => (
                      <li key={item.event_id}>
                        {gapAfter.has(item.event_id) && (
                          <div className="gap" role="note">
                            No location for {formatDuration(gapAfter.get(item.event_id) ?? 0)} before this point
                          </div>
                        )}
                        <div className="row between">
                          <span>{describe(item)}</span>
                          <span className="muted small">
                            <time dateTime={item.occurred_at}>{formatDateTime(item.occurred_at)}</time>
                          </span>
                        </div>
                        {Date.parse(item.received_at) - Date.parse(item.occurred_at) > 5 * 60_000 && (
                          <Chip tone="sky">Delivered late (saved on the phone while offline)</Chip>
                        )}
                      </li>
                    ))}
                  </ol>
                  {more && (
                    <button type="button" className="btn btn-soft" disabled={loading} onClick={() => void load(items.length)}>
                      {loading ? 'Loading…' : 'Load older events'}
                    </button>
                  )}
                </Card>
              </section>
            </>
          )}
        </>
      )}
    </>
  )
}
