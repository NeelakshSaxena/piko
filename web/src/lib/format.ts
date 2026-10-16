import { config } from '../config'
import type { DeviceStatus, Freshness } from '../api/types'

/** Age in whole seconds from an ISO timestamp; null when the time is missing or unparsable. */
export function ageSeconds(iso: string | null | undefined, nowMs: number): number | null {
  if (!iso) return null
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return null
  return Math.max(0, Math.floor((nowMs - then) / 1000))
}

export function formatAge(seconds: number | null): string {
  if (seconds === null) return 'never'
  if (seconds < 10) return 'just now'
  if (seconds < 60) return `${seconds} s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`
  return `${Math.floor(seconds / 86_400)} d ago`
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  if (seconds < 86_400) return `${Math.round(seconds / 360) / 10} h`
  return `${Math.round(seconds / 8640) / 10} d`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return 'unknown'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? 'unknown'
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/**
 * Freshness is recomputed from the capture time on every render, so a page left open never keeps
 * calling an old location "fresh". Thresholds match the API (5 min fresh, 24 h unknown).
 */
export function freshnessOf(occurredAt: string | null | undefined, nowMs: number): Freshness {
  const age = ageSeconds(occurredAt, nowMs)
  if (age === null) return 'unknown'
  if (age <= config.freshSeconds) return 'fresh'
  return age <= 86_400 ? 'stale' : 'unknown'
}

/** Unavailable data is "Unknown", never 0. */
export function batteryText(percent: number | null | undefined): string {
  return percent === null || percent === undefined ? 'Unknown' : `${percent}%`
}

export function deviceStatusText(status: DeviceStatus): string {
  return { online: 'Online', offline: 'Offline', unknown: 'Unknown' }[status]
}

export function accuracyText(meters: number | null | undefined): string {
  return meters === null || meters === undefined ? 'accuracy unknown' : `±${Math.round(meters)} m`
}

export function coordinateText(lat: number, lon: number): string {
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`
}

const NETWORK_LABELS: Record<string, string> = {
  wifi: 'Wi-Fi',
  cellular: 'Mobile data',
  ethernet: 'Ethernet',
  vpn: 'VPN',
  other: 'Other network',
  none: 'No connection',
}

/** Network type as the phone last reported it; null means it never reported one. */
export function networkText(type: string | null | undefined): string {
  if (!type) return 'Unknown'
  return NETWORK_LABELS[type] ?? type
}

export function chargingText(charging: boolean | null | undefined): string {
  if (charging === null || charging === undefined) return 'Charging state unknown'
  return charging ? 'Charging' : 'Not charging'
}

/** Seconds a reading took to reach the server after it was taken (large means it waited offline on the phone). */
export function deliveryDelaySeconds(occurredAt: string, receivedAt: string): number {
  return Math.max(0, Math.round((Date.parse(receivedAt) - Date.parse(occurredAt)) / 1000))
}

export const LATE_DELIVERY_SECONDS = 5 * 60
