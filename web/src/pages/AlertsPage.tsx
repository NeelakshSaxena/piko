import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { ChatMessage } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useFamily } from '../auth/FamilyContext'
import { useFleet } from '../auth/FleetContext'
import { useSos } from '../auth/SosContext'
import { PushSetup } from '../components/PushSetup'
import { Card, Chip, Empty, ErrorState, Loading, PageTitle } from '../components/ui'
import { ageSeconds, formatAge, formatDateTime } from '../lib/format'
import { STATUS_TEXT, sortNotices, statusNotices, type Notice } from '../lib/safety'
import { useAsync, useNow } from '../lib/useAsync'

const SEVERITY_TONE = { urgent: 'rose', attention: 'amber', info: 'grey' } as const
const SEVERITY_TEXT = { urgent: 'Needs action', attention: 'Worth a look', info: 'For information' } as const
const KIND_TEXT = { sos: 'SOS', message: 'Message', status: 'Phone status (derived)' } as const

/**
 * One list from three honest sources: incidents the server holds, child messages nobody has marked
 * as seen, and notices this page derives from the phone's last report. Nothing here is a push
 * notification; it is only as current as the last time this dashboard read the server.
 */
export function AlertsPage() {
  const { api } = useAuth()
  const { children } = useFamily()
  const fleet = useFleet()
  const sos = useSos()
  const now = useNow(15_000)
  const ids = children.flatMap((c) => c.devices.slice(0, 1).map((d) => ({ memberId: c.member.id, deviceId: d.id, name: d.name })))
  const messages = useAsync(
    async () => {
      const results = await Promise.allSettled(ids.map((x) => api.messages(x.deviceId, { limit: 50 })))
      return results.map((r, i) => ({ target: ids[i]!, page: r.status === 'fulfilled' ? r.value : null, error: r.status === 'rejected' ? r.reason : null }))
    },
    [api, ids.map((x) => x.deviceId).join(',')],
    30_000,
  )

  const notices: Notice[] = []
  for (const i of sos.state.data?.incidents ?? []) {
    const name = children.flatMap((c) => c.devices).find((d) => d.id === i.device_id)?.name ?? 'A phone'
    const recent = now - Date.parse(i.triggered_at) < 24 * 3600 * 1000
    if (i.status === 'resolved' && !recent) continue
    notices.push({
      id: `sos:${i.incident_id}`,
      severity: i.status === 'open' ? 'urgent' : i.status === 'acknowledged' ? 'attention' : 'info',
      kind: 'sos',
      title: `SOS from ${name}`,
      detail: `${STATUS_TEXT[i.status]}. Raised ${formatAge(ageSeconds(i.triggered_at, now))}.`,
      at: i.triggered_at,
      to: `/sos?incident=${i.incident_id}`,
    })
  }
  const failedConversations: string[] = []
  for (const row of messages.state.data ?? []) {
    if (row.error || !row.page) {
      failedConversations.push(row.target.name)
      continue
    }
    const unseen = row.page.messages.filter((m: ChatMessage) => m.sender === 'device' && m.status === 'delivered')
    if (unseen.length > 0) {
      notices.push({
        id: `msg:${row.target.deviceId}`,
        severity: 'attention',
        kind: 'message',
        title: `${unseen.length} message${unseen.length === 1 ? '' : 's'} from ${row.target.name} not marked as seen`,
        detail: `Latest delivered ${formatDateTime(unseen[0]?.received_at)}. Nobody has marked it as seen.`,
        at: unseen[0]?.received_at ?? null,
        to: `/messages?member=${row.target.memberId}`,
      })
    }
  }
  for (const entry of fleet.entries) {
    notices.push(...statusNotices({ id: entry.member.id, name: entry.device?.name ?? entry.member.name ?? 'A phone' }, entry.detail, entry.location, now))
  }
  const sorted = sortNotices(notices)

  const loading = (sos.state.status === 'loading' && !sos.state.data) || (messages.state.status === 'loading' && !messages.state.data)
  return (
    <>
      <PageTitle>Alerts</PageTitle>
      <Card tone="sky">
        <p>
          This list is built from what Piko has received, each time this dashboard reads it. <strong>These are not push notifications</strong>: if
          no dashboard is open, nobody is told. Notices marked &ldquo;derived&rdquo; are worked out here from the phone&rsquo;s last report and may be out of
          date.
        </p>
      </Card>

      <PushSetup />

      {sos.state.status === 'error' && <ErrorState error={sos.state.error} what="SOS incidents" onRetry={() => void sos.reload()} />}
      {messages.state.status === 'error' && <ErrorState error={messages.state.error as ApiError} what="messages" onRetry={() => void messages.reload()} />}
      {failedConversations.length > 0 && (
        <p className="warn" role="status">
          Messages from {failedConversations.join(', ')} could not be loaded, so unread messages from them are not listed.
        </p>
      )}
      {fleet.failing && (
        <p className="warn" role="status">
          Phone status could not be refreshed; the notices below use the last known values.
        </p>
      )}
      {loading && <Loading label="Loading alerts…" />}

      {!loading && sorted.length === 0 && sos.state.status !== 'error' && (
        <Empty title="No alerts right now">
          Nothing needs attention in what Piko has received. That is not proof that a child is safe: a phone that is off, offline or unlinked cannot raise anything.
        </Empty>
      )}

      {sorted.length > 0 && (
        <ul className="plain stack tight" aria-label="Alerts">
          {sorted.map((n) => (
            <li key={n.id}>
              <Card tone={n.severity === 'urgent' ? 'rose' : undefined}>
                <div className="row between">
                  <h2 className="h3">{n.title}</h2>
                  <span className="chips">
                    <Chip tone={SEVERITY_TONE[n.severity]}>{SEVERITY_TEXT[n.severity]}</Chip>
                    <Chip tone="lavender">{KIND_TEXT[n.kind]}</Chip>
                  </span>
                </div>
                <p>{n.detail}</p>
                <p>
                  <Link to={n.to}>{n.kind === 'sos' ? 'Open the incident' : n.kind === 'message' ? 'Open the conversation' : 'See the details'}</Link>
                  {n.at && (
                    <span className="muted small">
                      {' '}
                      · <time dateTime={n.at}>{formatDateTime(n.at)}</time>
                    </span>
                  )}
                </p>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
