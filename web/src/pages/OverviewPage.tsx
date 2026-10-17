import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import type { HistoryItem } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useFamily } from '../auth/FamilyContext'
import { useFleet, type FleetEntry } from '../auth/FleetContext'
import { useSos } from '../auth/SosContext'
import { Icon } from '../components/Icon'
import { FleetMap, TileNotice, type MapMarker } from '../components/Map'
import { Avatar, Card, Chip, Empty, ErrorState, FreshnessBadge, Loading, PageTitle, StatusBadge, Tile } from '../components/ui'
import { config } from '../config'
import { accuracyText, ageSeconds, batteryText, chargingText, formatAge, formatDateTime, freshnessOf, networkText } from '../lib/format'
import { useAsync, useNow } from '../lib/useAsync'

export function markersOf(entries: FleetEntry[], nowMs: number): MapMarker[] {
  return entries.flatMap((e): MapMarker[] => {
    const loc = e.location
    if (!loc?.available || !loc.coordinates) return []
    return [
      {
        id: e.member.id,
        label: e.member.name ?? 'Unnamed phone',
        lat: loc.coordinates.latitude,
        lon: loc.coordinates.longitude,
        accuracy: loc.accuracy_meters ?? null,
        fresh: freshnessOf(loc.occurred_at, nowMs) === 'fresh',
      },
    ]
  })
}

function greeting(now: Date): string {
  const h = now.getHours()
  return h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

function RosterCard({ entry, now }: { entry: FleetEntry; now: number }) {
  const { member, device, detail, location: loc } = entry
  // Freshness comes from the capture time, recomputed now, never from a label fetched minutes ago.
  const freshness = loc?.available ? freshnessOf(loc.occurred_at, now) : 'unknown'
  const age = ageSeconds(loc?.occurred_at, now)
  const name = member.name ?? 'Unnamed phone'
  return (
    <Card className="roster-card">
      <div className="row between">
        <div className="row">
          <Avatar name={name} />
          <div>
            <h3 className="h3">{name}</h3>
            <span className="muted small">{device ? 'Linked phone' : 'No phone linked'}</span>
          </div>
        </div>
        {loc ? <StatusBadge status={loc.device_status} /> : <Chip tone="grey">Checking…</Chip>}
      </div>

      {entry.error && (
        <p className="muted small" role="status">
          {loc || detail ? 'Could not refresh just now. Showing what was last loaded.' : entry.error.message}
        </p>
      )}

      <dl className="strip">
        <div>
          <dt>Location</dt>
          <dd>
            <FreshnessBadge freshness={freshness} ageSeconds={age} />
            {loc?.available && loc.accuracy_meters !== undefined && <span className="muted small"> {accuracyText(loc.accuracy_meters)}</span>}
          </dd>
        </div>
        <div>
          <dt>Battery</dt>
          <dd>
            {batteryText(detail?.battery_percent)}
            <span className="muted small"> · {chargingText(detail?.battery_is_charging)}</span>
          </dd>
        </div>
        <div>
          <dt>Network</dt>
          <dd>{networkText(detail?.network_type)}</dd>
        </div>
        <div>
          <dt>Last contact</dt>
          <dd>{device?.last_seen ? formatAge(ageSeconds(device.last_seen, now)) : 'Never'}</dd>
        </div>
      </dl>

      <div className="row">
        <Link className="btn btn-soft" to={`/map?member=${member.id}`}>
          View on Live Map
        </Link>
        <Link className="btn btn-soft" to={`/activity?member=${member.id}`}>
          Activity
        </Link>
        {device && (
          <Link className="btn btn-soft" to={`/health?device=${device.id}`}>
            Device health
          </Link>
        )}
      </div>
    </Card>
  )
}

function describe(item: HistoryItem): { title: string; detail: string } {
  const d = item.data
  if (item.event_type === 'location') {
    const acc = typeof d.accuracy_meters === 'number' ? accuracyText(d.accuracy_meters) : 'accuracy unknown'
    return { title: 'Location reported', detail: acc }
  }
  if (item.event_type === 'battery') {
    return { title: `Battery ${batteryText(typeof d.percent === 'number' ? d.percent : null)}`, detail: chargingText(typeof d.is_charging === 'boolean' ? d.is_charging : null) }
  }
  return { title: 'Network changed', detail: networkText(typeof d.network_type === 'string' ? d.network_type : null) }
}

function Timeline({ entries }: { entries: FleetEntry[] }) {
  const { api } = useAuth()
  const ids = entries.map((e) => e.member.id).join(',')
  const { state } = useAsync(
    async () => {
      const pages = await Promise.all(entries.map(async (e) => ({ e, page: await api.memberHistory(e.member.id, { limit: 6 }) })))
      return pages
        .flatMap(({ e, page }) => page.history.map((item) => ({ who: e.member.name ?? 'Unnamed phone', item })))
        .sort((a, b) => Date.parse(b.item.occurred_at) - Date.parse(a.item.occurred_at))
        .slice(0, 6)
    },
    [api, ids],
    config.refreshMs * 3,
  )
  return (
    <Card>
      <h2 className="h2">Safety Timeline</h2>
      {state.status === 'loading' && <Loading label="Loading recent activity…" />}
      {state.status === 'error' && !state.data && <ErrorState error={state.error} what="the timeline" />}
      {state.status !== 'loading' && state.data && state.data.length === 0 && <p className="muted">Nothing has been reported yet.</p>}
      {state.data && state.data.length > 0 && (
        <ol className="timeline compact">
          {state.data.map(({ who, item }) => {
            const d = describe(item)
            return (
              <li key={`${who}-${item.event_id}`}>
                <strong>{d.title}</strong>
                <span className="muted small">
                  {who} · {d.detail}
                </span>
                <time className="muted small" dateTime={item.occurred_at}>
                  {formatDateTime(item.occurred_at)}
                </time>
              </li>
            )
          })}
        </ol>
      )}
      <Link className="btn btn-soft" to="/activity">
        View complete activity log →
      </Link>
    </Card>
  )
}

export function OverviewPage() {
  const { canManage } = useAuth()
  const { family, reload } = useFamily()
  const { entries, loading, reload: reloadFleet } = useFleet()
  const { openCount } = useSos()
  const now = useNow(15_000)

  const markers = useMemo(() => markersOf(entries, now), [entries, now])
  const total = entries.length
  const online = entries.filter((e) => e.location?.device_status === 'online').length
  const offline = entries.filter((e) => e.location?.device_status === 'offline').length
  const unknownStatus = total - online - offline
  const freshest = entries
    .map((e) => (e.location?.available ? e.location.occurred_at : undefined))
    .filter((t): t is string => Boolean(t))
    .sort()
    .at(-1)
  const freshestAge = ageSeconds(freshest, now)

  return (
    <>
      <PageTitle>{greeting(new Date(now))}</PageTitle>
      <p className="muted">
        {family.data?.name ?? 'Your family'} · {total === 0 ? 'no phones linked yet' : `${total} ${total === 1 ? 'child' : 'children'} connected`}
      </p>
      {family.status === 'loading' && !family.data && <Loading label="Loading your family…" />}
      {family.status === 'error' && <ErrorState error={family.error} what="your family" onRetry={() => void reload()} />}

      {family.data && (
        <>
          <div className="tiles">
            <Tile
              tone="mint"
              icon={<Icon name="people" />}
              label="Phones reporting now"
              value={
                <>
                  {online} <span className="muted">/ {total}</span>
                </>
              }
              note={total === 0 ? 'No phones linked yet' : `${offline} offline · ${unknownStatus} not heard from`}
            />
            <Tile
              tone="sky"
              icon={<Icon name="signal" />}
              label="Freshest location"
              value={freshest ? formatAge(freshestAge) : 'None yet'}
              note={freshest ? 'Age of the newest position reported' : 'No phone has reported a position'}
            />
            <Tile
              tone="lavender"
              icon={<Icon name="battery" />}
              label="Lowest battery"
              value={(() => {
                const levels = entries.map((e) => e.detail?.battery_percent).filter((p): p is number => typeof p === 'number')
                return levels.length ? `${Math.min(...levels)}%` : 'Unknown'
              })()}
              note="Across phones that have reported one"
            />
            <Tile
              tone="peach"
              icon={<Icon name="sos" />}
              label="SOS"
              value={openCount === null ? 'Unknown' : openCount > 0 ? `${openCount} open` : 'None open'}
              note={
                openCount === null
                  ? 'SOS status could not be read. Do not assume there are none.'
                  : openCount > 0
                    ? 'Not yet acknowledged. Open the SOS Centre.'
                    : 'No SOS has reached Piko. That is not proof anyone is safe. Piko does not call emergency services.'
              }
            />
          </div>

          <div className="two-col">
            <section aria-labelledby="roster-h" className="stack">
              <div className="row between">
                <h2 id="roster-h" className="h2">
                  Family roster &amp; latest status
                </h2>
                <button type="button" className="btn btn-soft" onClick={() => void reloadFleet()}>
                  <Icon name="refresh" size={16} /> Refresh
                </button>
              </div>
              {entries.length === 0 && !loading && (
                <Empty title="No one is sharing yet">
                  {canManage ? (
                    <>
                      Link a child's phone to start. <Link to="/family">Create a pairing code</Link>.
                    </>
                  ) : (
                    'A parent can link a phone from the Family Members page.'
                  )}
                </Empty>
              )}
              {entries.length === 0 && loading && <Loading label="Loading phones…" />}
              {entries.map((entry) => (
                <RosterCard key={entry.member.id} entry={entry} now={now} />
              ))}

              <h2 className="h2">Map preview</h2>
              <FleetMap markers={markers} label="Where phones last reported" height={320} />
              <TileNotice />
            </section>

            <aside className="stack" aria-label="Recent activity">
              <Timeline entries={entries} />
            </aside>
          </div>
        </>
      )}
    </>
  )
}
