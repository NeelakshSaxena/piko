import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { config } from '../config'
import type { RouteShape } from '../lib/route'

export interface MapMarker {
  id: string
  label: string
  lat: number
  lon: number
  accuracy: number | null
  /** Only a genuinely fresh location is drawn as "current"; anything older is drawn faded. */
  fresh: boolean
}

export interface MapHandle {
  fitAll: () => void
  focus: (id: string) => void
}

const COLORS = { fresh: '#33845C', stale: '#B87A2C', route: '#5E4FA2', gap: '#777588' }

interface Props {
  markers: MapMarker[]
  selectedId?: string | null
  route?: RouteShape | null
  label: string
  height?: number
  onSelect?: (id: string) => void
  /** Zoom to this marker when it changes (used when someone is picked in a list). */
  autoFit?: 'selected' | 'all'
}

/**
 * One Leaflet map for every page. Markers are circle markers (no image assets, CSP-friendly).
 * Missing data is never bridged: route gaps are dashed grey lines.
 */
export const FleetMap = forwardRef<MapHandle, Props>(function FleetMap(
  { markers, selectedId, route, label, height = 380, onSelect, autoFit = 'all' },
  ref,
) {
  const host = useRef<HTMLDivElement | null>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const markersRef = useRef(markers)
  markersRef.current = markers

  useEffect(() => {
    if (!host.current) return
    const instance = L.map(host.current, { zoomControl: true, attributionControl: true }).setView([20, 0], 2)
    if (config.tileUrl) {
      L.tileLayer(config.tileUrl, { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(instance)
    }
    map.current = instance
    layer.current = L.layerGroup().addTo(instance)
    return () => {
      instance.remove()
      map.current = null
      layer.current = null
    }
  }, [])

  const fitAll = () => {
    const instance = map.current
    const points = markersRef.current.map((m): L.LatLngTuple => [m.lat, m.lon])
    if (!instance || points.length === 0) return
    if (points.length === 1 && points[0]) instance.setView(points[0], 16)
    else instance.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 16 })
  }
  const focus = (id: string) => {
    const target = markersRef.current.find((m) => m.id === id)
    if (target && map.current) map.current.setView([target.lat, target.lon], Math.max(map.current.getZoom(), 16))
  }
  useImperativeHandle(ref, () => ({ fitAll, focus }))

  useEffect(() => {
    const target = layer.current
    if (!target) return
    target.clearLayers()
    for (const m of markers) {
      const color = m.fresh ? COLORS.fresh : COLORS.stale
      const selected = m.id === selectedId
      if (m.accuracy !== null && (selected || markers.length === 1)) {
        L.circle([m.lat, m.lon], { radius: m.accuracy, color, weight: 1, fillOpacity: 0.12 }).addTo(target)
      }
      const dot = L.circleMarker([m.lat, m.lon], {
        radius: selected ? 12 : 9,
        color: '#ffffff',
        weight: 3,
        fillColor: color,
        fillOpacity: m.fresh ? 1 : 0.55,
      }).addTo(target)
      dot.bindTooltip(m.label, { permanent: true, direction: 'top', offset: [0, -10], className: 'map-label' })
      if (onSelect) dot.on('click', () => onSelect(m.id))
    }
    if (route) {
      for (const segment of route.segments) {
        const line = segment.map((p): L.LatLngTuple => [p.lat, p.lon])
        if (line.length > 1) L.polyline(line, { color: COLORS.route, weight: 4 }).addTo(target)
      }
      for (const gap of route.gaps) {
        L.polyline(
          [
            [gap.from.lat, gap.from.lon],
            [gap.to.lat, gap.to.lon],
          ],
          { color: COLORS.gap, weight: 2, dashArray: '6 8' },
        ).addTo(target)
      }
    }
  }, [markers, selectedId, route, onSelect])

  // Fit when the *set* of things shown changes, not on every refresh (that would fight the user's panning).
  const fitKey = route
    ? `route:${route.segments.length}:${route.segments[0]?.[0]?.at ?? ''}`
    : autoFit === 'selected'
      ? `sel:${selectedId ?? ''}`
      : `all:${markers.map((m) => m.id).join(',')}`
  useEffect(() => {
    const instance = map.current
    if (!instance) return
    if (route) {
      const all = route.segments.flat().map((p): L.LatLngTuple => [p.lat, p.lon])
      if (all.length > 0) instance.fitBounds(L.latLngBounds(all), { padding: [24, 24], maxZoom: 17 })
    } else if (autoFit === 'selected' && selectedId) focus(selectedId)
    else fitAll()
  }, [fitKey])

  return (
    <div
      ref={host}
      className="map"
      style={{ height }}
      role="img"
      aria-label={markers.length > 0 ? `${label}: ${markers.map((m) => m.label).join(', ')}` : `${label}: nothing to show`}
    />
  )
})

export function TileNotice() {
  return (
    <p className="muted small">
      {config.tileUrl
        ? 'Map tiles are loaded from the configured tile server, which can see roughly which area is being viewed. Operators can change or disable this.'
        : 'Map tiles are switched off by the operator. Positions are shown as markers and coordinates only.'}
    </p>
  )
}
