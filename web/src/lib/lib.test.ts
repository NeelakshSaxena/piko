import { describe, expect, it } from 'vitest'
import type { HistoryItem } from '../api/types'
import { accuracyText, ageSeconds, batteryText, formatAge, freshnessOf } from './format'
import { buildRoute, locationPoints } from './route'

const NOW = Date.parse('2026-10-16T12:00:00Z')
const at = (secondsAgo: number) => new Date(NOW - secondsAgo * 1000).toISOString()

describe('freshness', () => {
  it('is fresh only within five minutes and never "live"', () => {
    expect(freshnessOf(at(10), NOW)).toBe('fresh')
    expect(freshnessOf(at(300), NOW)).toBe('fresh')
    expect(freshnessOf(at(301), NOW)).toBe('stale')
    expect(freshnessOf(at(86_400), NOW)).toBe('stale')
    expect(freshnessOf(at(86_401), NOW)).toBe('unknown')
  })

  it('treats a missing or unparsable time as unknown, not as fresh', () => {
    expect(freshnessOf(null, NOW)).toBe('unknown')
    expect(freshnessOf(undefined, NOW)).toBe('unknown')
    expect(freshnessOf('not a date', NOW)).toBe('unknown')
  })

  it('a time in the future is age zero, not negative', () => {
    expect(ageSeconds(new Date(NOW + 60_000).toISOString(), NOW)).toBe(0)
  })
})

describe('formatting', () => {
  it('shows unavailable data as unknown, never zero', () => {
    expect(batteryText(null)).toBe('Unknown')
    expect(batteryText(undefined)).toBe('Unknown')
    expect(batteryText(0)).toBe('0%')
    expect(accuracyText(null)).toBe('accuracy unknown')
    expect(formatAge(null)).toBe('never')
  })

  it('words ages sensibly', () => {
    expect(formatAge(3)).toBe('just now')
    expect(formatAge(45)).toBe('45 s ago')
    expect(formatAge(180)).toBe('3 min ago')
    expect(formatAge(7200)).toBe('2 h ago')
  })
})

function loc(secondsAgo: number, lat: number): HistoryItem {
  return {
    event_id: `e${secondsAgo}`, occurred_at: at(secondsAgo), received_at: at(secondsAgo - 1), event_type: 'location',
    freshness: 'stale', data: { latitude: lat, longitude: 10, accuracy_meters: 5 },
  }
}

describe('route building', () => {
  it('orders newest-first history oldest to newest and ignores non-location events', () => {
    const items: HistoryItem[] = [
      loc(60, 3),
      { ...loc(90, 0), event_type: 'battery', data: { percent: 50 } },
      loc(120, 2),
      loc(180, 1),
    ]
    expect(locationPoints(items).map((p) => p.lat)).toEqual([1, 2, 3])
  })

  it('splits at gaps instead of drawing a line through missing time', () => {
    const points = locationPoints([loc(60, 4), loc(120, 3), loc(4000, 2), loc(4060, 1)])
    const shape = buildRoute(points, 900)
    expect(shape.segments.map((s) => s.length)).toEqual([2, 2])
    expect(shape.gaps).toHaveLength(1)
    expect(shape.gaps[0]?.seconds).toBeGreaterThan(3800)
  })

  it('does not report a gap at exactly the threshold and handles an empty route', () => {
    expect(buildRoute(locationPoints([loc(900, 1), loc(0, 2)]), 900).gaps).toHaveLength(0)
    expect(buildRoute([], 900)).toEqual({ segments: [], gaps: [] })
  })

  it('skips events whose coordinates are not numbers', () => {
    const bad: HistoryItem = { ...loc(10, 1), data: { latitude: '1', longitude: null } }
    expect(locationPoints([bad])).toEqual([])
  })
})
