import type { HistoryItem } from '../api/types'

export interface RoutePoint {
  lat: number
  lon: number
  at: string
  accuracy: number | null
}

export interface RouteGap {
  from: RoutePoint
  to: RoutePoint
  seconds: number
}

export interface RouteShape {
  /** Continuous stretches of travel, oldest point first. */
  segments: RoutePoint[][]
  /** Places where no location was reported for longer than the gap threshold. */
  gaps: RouteGap[]
}

export function locationPoints(items: HistoryItem[]): RoutePoint[] {
  const points: RoutePoint[] = []
  for (const item of items) {
    if (item.event_type !== 'location') continue
    const lat = item.data.latitude
    const lon = item.data.longitude
    if (typeof lat !== 'number' || typeof lon !== 'number') continue
    const accuracy = typeof item.data.accuracy_meters === 'number' ? item.data.accuracy_meters : null
    points.push({ lat, lon, at: item.occurred_at, accuracy })
  }
  // The API returns newest first; a route reads oldest to newest.
  return points.sort((a, b) => Date.parse(a.at) - Date.parse(b.at))
}

/** Splits a route wherever consecutive fixes are further apart than `gapSeconds`, so missing data is visible, never bridged. */
export function buildRoute(points: RoutePoint[], gapSeconds: number): RouteShape {
  const segments: RoutePoint[][] = []
  const gaps: RouteGap[] = []
  let current: RoutePoint[] = []
  for (const point of points) {
    const previous = current[current.length - 1]
    if (previous) {
      const seconds = (Date.parse(point.at) - Date.parse(previous.at)) / 1000
      if (seconds > gapSeconds) {
        gaps.push({ from: previous, to: point, seconds: Math.round(seconds) })
        segments.push(current)
        current = []
      }
    }
    current.push(point)
  }
  if (current.length > 0) segments.push(current)
  return { segments, gaps }
}
