import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { HistoryItem } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useFamily } from '../auth/FamilyContext'
import { useFleet } from '../auth/FleetContext'
import { Icon } from '../components/Icon'
import { Avatar, Card, Chip, Empty, ErrorState, FreshnessBadge, Loading, PageTitle, StatusBadge, Tile } from '../components/ui'
import { config } from '../config'
import {
  LATE_DELIVERY_SECONDS, accuracyText, ageSeconds, batteryText, chargingText, deliveryDelaySeconds, formatAge, formatDateTime, freshnessOf, networkText,
} from '../lib/format'
import { useAsync, useNow } from '../lib/useAsync'

function attributes(item: HistoryItem): string {
  const d = item.data
  if (item.event_type === 'location') {
    return `${typeof d.latitude === 'number' ? d.latitude.toFixed(5) : '?'}, ${typeof d.longitude === 'number' ? d.longitude.toFixed(5) : '?'} · ${accuracyText(typeof d.accuracy_meters === 'number' ? d.accuracy_meters : null)}`
  }
  if (item.event_type === 'battery') {
    return `${batteryText(typeof d.percent === 'number' ? d.percent : null)} · ${chargingText(typeof d.is_charging === 'boolean' ? d.is_charging : null)}`
  }
  return networkText(typeof d.network_type === 'string' ? d.network_type : null)
}

const EVENT_LABEL = { location: 'Location', battery: 'Battery', connectivity: 'Network change' } as const

function csvCell(value: string): string {
  // Guard against spreadsheet formula injection as well as quoting.
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value
  return `"${safe.replace(/"/g, '""')}"`
}

/** Builds the export from what is already on screen, so no extra data leaves the server. */
export function eventsToCsv(items: HistoryItem[]): string {
  const rows = items.map((i) =>
    [i.occurred_at, i.received_at, i.event_type, attributes(i), String(deliveryDelaySeconds(i.occurred_at, i.received_at))].map(csvCell).join(','),
  )
  return ['occurred_at,received_at,event_type,details,delivery_delay_seconds', ...rows].join('\r\n')
}

export function HealthPage() {
  const { api, canManage } = useAuth()
  const { children, reload: reloadFamily } = useFamily()
  const { entries, reload: reloadFleet } = useFleet()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const now = useNow(10_000)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<ApiError | null>(null)

  const withPhone = entries.filter((e) => e.device)
  const entry = withPhone.find((e) => e.device?.id === params.get('device')) ?? withPhone[0]
  const device = entry?.device
  const detail = entry?.detail
  const loc = entry?.location

  const history = useAsync(
    () => (entry ? api.memberHistory(entry.member.id, { limit: 100 }) : Promise.resolve(null)),
    [api, entry?.member.id],
    config.refreshMs * 2,
  )
  const events = history.state.data?.history ?? []
  const late = events.filter((e) => deliveryDelaySeconds(e.occurred_at, e.received_at) > LATE_DELIVERY_SECONDS).length
  const freshness = loc?.available ? freshnessOf(loc.occurred_at, now) : 'unknown'
  const [csvUrl, setCsvUrl] = useState<string | null>(null)
  useEffect(() => {
    if (events.length === 0) {
      setCsvUrl(null)
      return
    }
    const url = URL.createObjectURL(new Blob([eventsToCsv(events)], { type: 'text/csv;charset=utf-8' }))
    setCsvUrl(url)
    return () => URL.revokeObjectURL(url) // do not leak a blob per refresh
  }, [history.state.data])

  async function unlink() {
    if (!device) return
    setBusy(true)
    setFailure(null)
    try {
      await api.revokeDevice(device.id)
      await reloadFamily()
      await reloadFleet()
      navigate('/family', { replace: true })
    } catch (e) {
      setFailure(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', 'Could not unlink this phone.'))
      setBusy(false)
      setConfirming(false)
    }
  }

  return (
    <>
      <PageTitle>Device Health &amp; Connectivity</PageTitle>
      <p className="muted">What each phone has reported: battery, network, location quality and delivery. Values the phone has not reported show as Unknown.</p>
      {withPhone.length === 0 && children.length === 0 && <Empty title="No phones yet">Link a child's phone from Family Members to see its health here.</Empty>}

      {withPhone.length > 1 && (
        <div className="chips" role="group" aria-label="Choose a phone">
          {withPhone.map((e) => (
            <button key={e.device?.id} type="button" className={`pill ${e.device?.id === device?.id ? 'on' : ''}`} aria-pressed={e.device?.id === device?.id} onClick={() => setParams({ device: e.device?.id ?? '' })}>
              {e.device?.name}
            </button>
          ))}
        </div>
      )}

      {entry && device && (
        <>
          <div className="row">
            <Avatar name={entry.member.name ?? '?'} />
            <div>
              <h2 className="h2 flush">{device.name}</h2>
              <span className="muted small">
                {detail?.device_model ?? 'Unknown model'} · Android {detail?.android_version ?? 'unknown'} · app {detail?.app_version ?? 'unknown'}
              </span>
            </div>
            {detail && <StatusBadge status={detail.connectivity_status} />}
            {detail?.status === 'revoked' && <Chip tone="rose">Unlinked</Chip>}
          </div>
          {entry.error && <ErrorState error={entry.error} what="this phone" onRetry={() => void reloadFleet()} />}

          <div className="tiles">
            <Tile tone="mint" icon={<Icon name="shield" />} label="Device status" value={detail ? (detail.connectivity_status === 'online' ? 'Reporting' : detail.connectivity_status === 'offline' ? 'Silent' : 'Never heard from') : 'Loading…'} note="Inferred from when the phone last contacted the server" />
            <Tile tone="lavender" icon={<Icon name="battery" />} label="Battery" value={batteryText(detail?.battery_percent)} note={`${chargingText(detail?.battery_is_charging)}${detail?.battery_updated_at ? ` · reported ${formatAge(ageSeconds(detail.battery_updated_at, now))}` : ''}`} />
            <Tile tone="sky" icon={<Icon name="signal" />} label="Network link" value={networkText(detail?.network_type)} note={detail?.network_updated_at ? `reported ${formatAge(ageSeconds(detail.network_updated_at, now))}` : 'Never reported'} />
            <Tile tone="peach" icon={<Icon name="clock" />} label="Last contact" value={device.last_seen ? formatAge(ageSeconds(device.last_seen, now)) : 'Never'} note={device.last_seen ? formatDateTime(device.last_seen) : 'The phone has not contacted the server'} />
          </div>

          <div className="three-col">
            <Card>
              <h2 className="h2">Battery &amp; power</h2>
              <div className="ring-row">
                <div className="ring" role="img" aria-label={`Battery ${batteryText(detail?.battery_percent)}`} style={{ ['--pct' as string]: `${detail?.battery_percent ?? 0}` }}>
                  <span>{batteryText(detail?.battery_percent)}</span>
                </div>
                <div>
                  <strong>{chargingText(detail?.battery_is_charging)}</strong>
                  <div className="muted small">{detail?.battery_updated_at ? `Reported ${formatDateTime(detail.battery_updated_at)}` : 'No battery report yet'}</div>
                </div>
              </div>
              <p className="muted small">Temperature, health and power-saving settings are not reported by the phone app.</p>
            </Card>

            <Card>
              <h2 className="h2">Location quality</h2>
              <div className="stack tight">
                <FreshnessBadge freshness={freshness} ageSeconds={ageSeconds(loc?.occurred_at, now)} />
                <dl className="kv">
                  <div><dt>Accuracy</dt><dd>{loc?.available ? accuracyText(loc.accuracy_meters) : 'Unknown'}</dd></div>
                  <div><dt>Fix taken</dt><dd>{loc?.occurred_at ? formatDateTime(loc.occurred_at) : 'Never'}</dd></div>
                  <div><dt>Received</dt><dd>{loc?.received_at ? formatDateTime(loc.received_at) : 'Never'}</dd></div>
                </dl>
                <p className="muted small">Satellite counts and sensor details are not reported by the phone app.</p>
              </div>
            </Card>

            <Card>
              <h2 className="h2">Delivery &amp; sync</h2>
              <dl className="kv">
                <div><dt>Recent events</dt><dd>{history.state.status === 'loading' && !history.state.data ? '…' : events.length}</dd></div>
                <div><dt>Delivered late</dt><dd>{history.state.data ? `${late} of ${events.length}` : '…'}</dd></div>
                <div><dt>Linked</dt><dd>{formatDateTime(device.paired_at)}</dd></div>
              </dl>
              <p className="muted small">"Late" means a reading reached the server more than {Math.round(LATE_DELIVERY_SECONDS / 60)} minutes after it was taken: the phone was offline and delivered it when it reconnected, with its original time.</p>
            </Card>
          </div>

          <Card>
            <div className="row between">
              <div>
                <h2 className="h2">Recent telemetry &amp; connection events</h2>
                <p className="muted small">Newest first. Times are when each reading was taken on the phone.</p>
              </div>
              {csvUrl && (
                <a className="btn btn-soft" href={csvUrl} download={`piko-${device.name.replace(/[^\w-]+/g, '_')}-events.csv`}>
                  <Icon name="download" size={16} /> Export CSV
                </a>
              )}
            </div>
            {history.state.status === 'error' && <ErrorState error={history.state.error} what="events" onRetry={() => void history.reload()} />}
            {history.state.status === 'loading' && !history.state.data && <Loading label="Loading events…" />}
            {history.state.data && events.length === 0 && <p className="muted">No events yet.</p>}
            {events.length > 0 && (
              <div className="table-wrap">
                <table className="table">
                  <caption className="sr-only">Recent events from {device.name}</caption>
                  <thead>
                    <tr><th scope="col">Time</th><th scope="col">Event</th><th scope="col">Details</th><th scope="col">Delivery</th></tr>
                  </thead>
                  <tbody>
                    {events.slice(0, 25).map((e) => {
                      const delay = deliveryDelaySeconds(e.occurred_at, e.received_at)
                      return (
                        <tr key={e.event_id}>
                          <td><time dateTime={e.occurred_at}>{formatDateTime(e.occurred_at)}</time></td>
                          <td>{EVENT_LABEL[e.event_type]}</td>
                          <td>{attributes(e)}</td>
                          <td>{delay > LATE_DELIVERY_SECONDS ? <Chip tone="sky">Delivered late ({formatAge(delay)})</Chip> : <Chip tone="mint">On time</Chip>}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {canManage && detail?.status !== 'revoked' && (
            <Card tone="peach">
              <h2 className="h2">Unlink this phone</h2>
              <p>The phone stops being able to send location immediately. Its history stays in the family record until it expires.</p>
              {failure && <ErrorState error={failure} what="that" />}
              {!confirming ? (
                <button type="button" className="btn btn-soft" onClick={() => setConfirming(true)}>
                  Unlink…
                </button>
              ) : (
                <div className="row" role="group" aria-label="Confirm unlinking">
                  <button type="button" className="btn btn-danger" disabled={busy} onClick={() => void unlink()}>
                    {busy ? 'Unlinking…' : 'Yes, unlink this phone'}
                  </button>
                  <button type="button" className="btn btn-soft" onClick={() => setConfirming(false)}>
                    Cancel
                  </button>
                </div>
              )}
            </Card>
          )}
        </>
      )}
    </>
  )
}
