import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { Incident, SosStatus } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useFamily } from '../auth/FamilyContext'
import { useSos } from '../auth/SosContext'
import { FleetMap, TileNotice } from '../components/Map'
import { Card, Chip, Empty, ErrorState, FreshnessBadge, Loading, PageTitle } from '../components/ui'
import { config } from '../config'
import { accuracyText, coordinateText, formatAge, formatDateTime, formatDuration } from '../lib/format'
import { LATE_ARRIVAL_SECONDS, STATUS_TEXT, arrivalDelaySeconds, locationNote, sortIncidents } from '../lib/safety'
import { useNow } from '../lib/useAsync'

const STATUS_TONE = { open: 'rose', acknowledged: 'amber', resolved: 'mint' } as const

function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError(0, 'UNKNOWN', 'Something went wrong.')
}

function actionMessage(error: ApiError): string {
  if (error.status === 409) {
    return 'This incident changed while you were looking at it (someone may already have acknowledged or resolved it). The list has been refreshed.'
  }
  if (error.denied) return 'The server did not allow this. Your role in the family may be view-only.'
  if (error.code === 'NETWORK') return 'Cannot reach the Piko server. Nothing was changed. Try again when you are connected.'
  if (error.code === 'RATE_LIMIT') return 'Too many requests. Wait a moment and try again.'
  return `The change was not saved (${error.message}).`
}

function LocationBlock({ incident, now }: { incident: Incident; now: number }) {
  const note = locationNote(incident, now)
  const loc = incident.location
  if (!loc || note.kind === 'none') {
    return (
      <p>
        <strong>Location:</strong> No position was sent with this SOS and Piko had no recent one to attach.
      </p>
    )
  }
  return (
    <div className="stack tight">
      <div className="chips">
        {note.currency === 'historical' ? (
          <Chip tone="grey">Recorded position · captured {formatAge(note.ageSeconds)}</Chip>
        ) : (
          <FreshnessBadge freshness={note.currency === 'fresh' ? 'fresh' : 'stale'} ageSeconds={note.ageSeconds} />
        )}
        <Chip tone={note.kind === 'latest-known' ? 'amber' : 'sky'}>
          {note.kind === 'latest-known' ? 'Last known position, not sent with the SOS' : 'Measured by the phone when the SOS was raised'}
        </Chip>
      </div>
      <p>
        <strong>Position:</strong> {coordinateText(loc.latitude, loc.longitude)} ({accuracyText(loc.accuracy_meters)}), captured{' '}
        <time dateTime={loc.captured_at}>{formatDateTime(loc.captured_at)}</time>.
      </p>
      {note.kind === 'latest-known' && (
        <p className="muted small">
          This is the last position Piko knew before the SOS. The child may not be there now, or when they pressed the button.
        </p>
      )}
      {note.currency !== 'fresh' && note.currency !== 'historical' && (
        <p className="muted small">This position is not current. Do not treat it as where the child is right now.</p>
      )}
    </div>
  )
}

function IncidentCard({
  incident, deviceName, now, selected, canManage, busy, error, onSelect, onAcknowledge, onResolve,
}: {
  incident: Incident
  deviceName: string
  now: number
  selected: boolean
  canManage: boolean
  busy: boolean
  error: string | null
  onSelect: () => void
  onAcknowledge: () => void
  onResolve: (notes: string) => void
}) {
  const [confirming, setConfirming] = useState(false)
  const [notes, setNotes] = useState('')
  const delay = arrivalDelaySeconds(incident)
  const unresolved = incident.status !== 'resolved'
  const headingId = `inc-${incident.incident_id}`
  return (
    <li>
      <article className={`card incident incident-${incident.status}${selected ? ' selected' : ''}`} aria-labelledby={headingId}>
        <div className="row between">
          <h3 id={headingId} className="h3">
            {deviceName}
          </h3>
          <Chip tone={STATUS_TONE[incident.status]}>{STATUS_TEXT[incident.status]}</Chip>
        </div>
        <p>
          <strong>Raised:</strong> <time dateTime={incident.triggered_at}>{formatDateTime(incident.triggered_at)}</time> ·{' '}
          <strong>Reached Piko:</strong> <time dateTime={incident.received_at}>{formatDateTime(incident.received_at)}</time>
        </p>
        {delay > LATE_ARRIVAL_SECONDS && (
          <Chip tone="sky">Reached Piko {formatDuration(delay)} after it was raised (saved on the phone while offline)</Chip>
        )}
        {incident.message && (
          <p>
            <strong>Note from the child:</strong> <span className="user-text">{incident.message}</span>
          </p>
        )}
        <LocationBlock incident={incident} now={now} />
        {incident.acknowledged_at && (
          <p className="muted small">
            Acknowledged <time dateTime={incident.acknowledged_at}>{formatDateTime(incident.acknowledged_at)}</time>.
          </p>
        )}
        {incident.resolved_at && (
          <p className="muted small">
            Resolved <time dateTime={incident.resolved_at}>{formatDateTime(incident.resolved_at)}</time>.
          </p>
        )}
        {incident.parent_notes && (
          <p>
            <strong>Parent note:</strong> <span className="user-text">{incident.parent_notes}</span>
          </p>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="row actions">
          {incident.location && !selected && (
            <button type="button" className="btn btn-soft" onClick={onSelect}>
              Show on map
            </button>
          )}
          {canManage && incident.status === 'open' && (
            <button type="button" className="btn btn-primary" disabled={busy} onClick={onAcknowledge}>
              Acknowledge
            </button>
          )}
          {canManage && unresolved && !confirming && (
            <button type="button" className="btn btn-soft" disabled={busy} onClick={() => setConfirming(true)}>
              Mark as resolved…
            </button>
          )}
        </div>
        {canManage && incident.status === 'open' && (
          <p className="muted small">Acknowledging tells the child that a parent has seen the SOS. It does not resolve it.</p>
        )}
        {!canManage && unresolved && (
          <p className="muted small">Guardians can view incidents but cannot acknowledge or resolve them.</p>
        )}
        {confirming && unresolved && (
          <div className="confirm" role="group" aria-label={`Resolve the SOS from ${deviceName}`}>
            <p>
              <strong>Mark this SOS as resolved?</strong> Only do this when you know the child is safe. A resolved SOS cannot be reopened.
            </p>
            <label>
              Optional note (kept with the incident)
              <textarea rows={2} maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </label>
            <div className="row actions">
              <button
                type="button"
                className="btn btn-danger"
                disabled={busy}
                onClick={() => {
                  setConfirming(false)
                  onResolve(notes.trim())
                }}
              >
                Yes, mark as resolved
              </button>
              <button type="button" className="btn btn-soft" onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </article>
    </li>
  )
}

export function SosPage() {
  const { api, canManage } = useAuth()
  const { family } = useFamily()
  const sos = useSos()
  const now = useNow(15_000)
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = useState<'all' | SosStatus>('all')
  const [busy, setBusy] = useState<string | null>(null)
  const [failure, setFailure] = useState<{ id: string; message: string } | null>(null)

  const deviceNames = useMemo(() => {
    const map = new Map<string, string>()
    for (const d of family.data?.devices ?? []) map.set(d.id, d.name)
    return map
  }, [family.data])

  const all = useMemo(() => sortIncidents(sos.state.data?.incidents ?? []), [sos.state.data])
  const shown = filter === 'all' ? all : all.filter((i) => i.status === filter)
  const requested = params.get('incident')
  const selected =
    all.find((i) => i.incident_id === requested) ?? all.find((i) => i.status !== 'resolved' && i.location) ?? all.find((i) => i.location)
  const marker =
    selected?.location
      ? [{
          id: selected.incident_id,
          label: deviceNames.get(selected.device_id) ?? 'SOS',
          lat: selected.location.latitude,
          lon: selected.location.longitude,
          accuracy: selected.location.accuracy_meters,
          fresh: locationNote(selected, now).currency === 'fresh',
        }]
      : []

  async function change(incident: Incident, status: 'acknowledged' | 'resolved', notes?: string) {
    setBusy(incident.incident_id)
    setFailure(null)
    try {
      await api.updateSos(incident.incident_id, status, notes || undefined)
      await sos.reload()
    } catch (error) {
      const err = toApiError(error)
      setFailure({ id: incident.incident_id, message: actionMessage(err) })
      if (err.status === 409) await sos.reload()
    } finally {
      setBusy(null)
    }
  }

  const loadedFirstTime = sos.state.data !== null
  return (
    <>
      <PageTitle>SOS Centre</PageTitle>
      <Card tone="peach">
        <p>
          <strong>Piko does not contact emergency services.</strong> If a child may be in danger, call your local emergency number first.
        </p>
        <p className="muted small">
          This page re-reads incidents about every {Math.round(config.sosRefreshMs / 1000)} seconds while it is open. Piko cannot alert you if no dashboard is open, so an SOS
          is only seen here once a dashboard is looking.
        </p>
      </Card>

      {sos.state.status === 'loading' && !loadedFirstTime && <Loading label="Loading SOS incidents…" />}
      {sos.state.status === 'error' && <ErrorState error={sos.state.error} what="SOS incidents" onRetry={() => void sos.reload()} />}

      {loadedFirstTime && (
        <>
          {sos.state.status === 'error' && (
            <p className="warn" role="status">
              These incidents are the last ones that loaded and may be out of date.
            </p>
          )}
          <Card>
            <div className="filters">
              <label>
                Show
                <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
                  <option value="all">All incidents</option>
                  <option value="open">Open (not acknowledged)</option>
                  <option value="acknowledged">Acknowledged (not resolved)</option>
                  <option value="resolved">Resolved</option>
                </select>
              </label>
              <button type="button" className="btn btn-soft" onClick={() => void sos.reload()}>
                Refresh
              </button>
            </div>
          </Card>

          {sos.state.data?.truncated && (
            <p className="warn" role="status">
              Only the most recent incidents and every open one are loaded ({sos.state.data.incidents.length} of {sos.state.data.totalCount}). Older
              acknowledged or resolved incidents are not listed here.
            </p>
          )}
          {all.length === 0 && (
            <Empty title="No SOS incidents">
              Nothing has been raised. This does not mean everyone is safe; it only means Piko has not received an SOS. Phones that are
              offline, unlinked or without the app open cannot reach Piko.
            </Empty>
          )}
          {all.length > 0 && shown.length === 0 && <Empty title="Nothing matches this filter" />}

          {selected && marker.length > 0 && (
            <section aria-labelledby="sos-map-h">
              <h2 id="sos-map-h" className="h2">
                Where the position was
              </h2>
              <FleetMap markers={marker} selectedId={selected.incident_id} label="SOS position" height={320} autoFit="selected" />
              <TileNotice />
            </section>
          )}

          {shown.length > 0 && (
            <section aria-labelledby="sos-list-h">
              <h2 id="sos-list-h" className="h2">
                Incidents{' '}
                <span className="muted small">
                  ({shown.length}
                  {sos.state.data?.truncated ? `, ${sos.state.data.incidents.length} of ${sos.state.data.totalCount} loaded` : ''})
                </span>
              </h2>
              <ul className="plain stack">
                {shown.map((incident) => (
                  <IncidentCard
                    key={incident.incident_id}
                    incident={incident}
                    deviceName={deviceNames.get(incident.device_id) ?? 'A phone that is no longer in this family'}
                    now={now}
                    selected={selected?.incident_id === incident.incident_id}
                    canManage={canManage}
                    busy={busy === incident.incident_id}
                    error={failure?.id === incident.incident_id ? failure.message : null}
                    onSelect={() => setParams({ incident: incident.incident_id })}
                    onAcknowledge={() => void change(incident, 'acknowledged')}
                    onResolve={(notes) => void change(incident, 'resolved', notes)}
                  />
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </>
  )
}
