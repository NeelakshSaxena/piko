import type { DeviceDetail, Incident, MemberLocation, SosStatus } from '../api/types'
import { config } from '../config'
import { ageSeconds, formatAge, freshnessOf } from './format'

/** Wording for server states. "Open" never implies anyone has seen it; "acknowledged" never implies it is over. */
export const STATUS_TEXT: Record<SosStatus, string> = {
  open: 'Open · not yet acknowledged',
  acknowledged: 'Acknowledged · not resolved',
  resolved: 'Resolved',
}

/** Unresolved first (open before acknowledged), then newest first. */
export function sortIncidents(list: Incident[]): Incident[] {
  const rank = (i: Incident) => (i.status === 'open' ? 0 : i.status === 'acknowledged' ? 1 : 2)
  return [...list].sort((a, b) => rank(a) - rank(b) || Date.parse(b.triggered_at) - Date.parse(a.triggered_at))
}

/** Seconds between the phone raising the SOS and the server storing it (large: it waited offline). */
export function arrivalDelaySeconds(i: Pick<Incident, 'triggered_at' | 'received_at'>): number {
  return Math.max(0, Math.round((Date.parse(i.received_at) - Date.parse(i.triggered_at)) / 1000))
}

export const LATE_ARRIVAL_SECONDS = 5 * 60

export interface LocationNote {
  kind: 'none' | 'sent-with-sos' | 'latest-known'
  /** fresh: measured within 5 min of now. stale: older, within 24 h. historical: older than 24 h (a record, not a position). */
  currency: 'fresh' | 'stale' | 'historical' | 'none'
  ageSeconds: number | null
}

/**
 * Where an incident's position came from and how current it still is. Currency is always measured
 * from the capture time against *now*, so an old SOS never looks like a live position.
 */
export function locationNote(i: Pick<Incident, 'location'>, nowMs: number): LocationNote {
  const loc = i.location
  if (!loc) return { kind: 'none', currency: 'none', ageSeconds: null }
  const age = ageSeconds(loc.captured_at, nowMs)
  const f = freshnessOf(loc.captured_at, nowMs)
  return {
    kind: loc.is_latest_known ? 'latest-known' : 'sent-with-sos',
    currency: f === 'fresh' ? 'fresh' : f === 'stale' ? 'stale' : 'historical',
    ageSeconds: age,
  }
}

export interface Notice {
  id: string
  severity: 'urgent' | 'attention' | 'info'
  kind: 'sos' | 'message' | 'status'
  title: string
  detail: string
  at: string | null
  to: string
}

const SEVERITY_RANK = { urgent: 0, attention: 1, info: 2 } as const

export function sortNotices(list: Notice[]): Notice[] {
  return [...list].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || Date.parse(b.at ?? '') - Date.parse(a.at ?? '') || 0)
}

export const LOW_BATTERY_PERCENT = 20

/**
 * Notices derived in the browser from what the phone last reported. They are not events the server
 * raised and nobody is notified of them: they exist only while this dashboard is open.
 */
export function statusNotices(
  child: { id: string; name: string },
  detail: DeviceDetail | null,
  location: MemberLocation | null,
  nowMs: number,
): Notice[] {
  const out: Notice[] = []
  const to = `/health`
  if (detail) {
    if (detail.connectivity_status === 'offline') {
      out.push({
        id: `offline:${child.id}`, severity: 'attention', kind: 'status', to, at: detail.last_activity,
        title: `${child.name} has gone quiet`,
        detail: `Piko last heard from this phone ${formatAge(ageSeconds(detail.last_activity, nowMs))}. It may be offline, switched off or have sharing stopped.`,
      })
    } else if (detail.connectivity_status === 'unknown') {
      out.push({
        id: `never:${child.id}`, severity: 'info', kind: 'status', to, at: null,
        title: `${child.name} has not reported yet`,
        detail: 'This phone is linked but has not sent anything to Piko.',
      })
    }
    if (
      detail.battery_percent !== null && detail.battery_percent <= LOW_BATTERY_PERCENT &&
      detail.battery_is_charging === false
    ) {
      out.push({
        id: `battery:${child.id}`, severity: 'attention', kind: 'status', to, at: detail.battery_updated_at,
        title: `${child.name}'s battery was low`,
        detail: `${detail.battery_percent}% and not charging, as reported ${formatAge(ageSeconds(detail.battery_updated_at, nowMs))}. It may have changed since.`,
      })
    }
  }
  if (location && location.freshness !== 'fresh' && detail?.connectivity_status !== 'unknown') {
    out.push({
      id: `location:${child.id}`, severity: 'info', kind: 'status', to: '/map', at: location.occurred_at ?? null,
      title: `No current location for ${child.name}`,
      detail: location.available
        ? `The last position is ${formatAge(location.freshness_seconds)} old, older than ${Math.round(config.freshSeconds / 60)} minutes, so it is not shown as current.`
        : 'Piko has no recent position for this phone.',
    })
  }
  return out
}
