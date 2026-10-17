/** Build-time settings (VITE_*). Nothing secret belongs here: this file ships to every browser. */

const DEFAULT_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'

export const config = {
  /** Origin of the Piko API, without a path. */
  apiBase: (import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000').replace(/\/+$/, ''),
  /**
   * Raster tile URL template, or null for a coordinates-only map. Every tile request tells the tile
   * server roughly where the family is, so operators may point this at their own server or switch it
   * off with VITE_TILE_URL=off.
   */
  tileUrl: ((): string | null => {
    const value = import.meta.env.VITE_TILE_URL ?? DEFAULT_TILES
    return value === 'off' || value === '' ? null : value
  })(),
  /** A location older than this is never presented as current (matches the API's freshness rule). */
  freshSeconds: 5 * 60,
  /** Consecutive location events further apart than this are shown as a gap in the route. */
  gapSeconds: 15 * 60,
  /** How often visible pages re-read data. Each location read is recorded in the audit log. */
  refreshMs: 60_000,
  /** SOS data is re-read more often while a tab is visible. Dashboards are not pushed anything. */
  sosRefreshMs: 30_000,
} as const
