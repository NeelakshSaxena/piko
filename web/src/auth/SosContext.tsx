import { createContext, useContext, useMemo, type ReactNode } from 'react'
import type { Incident } from '../api/types'
import { config } from '../config'
import { useAsync, type AsyncState } from '../lib/useAsync'
import { useAuth } from './AuthContext'

export interface SosData {
  /** Recent incidents plus every open one, newest first, without duplicates. */
  incidents: Incident[]
  /** All incidents the server holds. */
  totalCount: number
  /** True when older incidents exist that are not in `incidents` (the page says so). */
  truncated: boolean
  /** Open incidents exactly as the server counts them (never derived from a truncated page). */
  openCount: number
}

interface SosApi {
  state: AsyncState<SosData>
  reload: () => Promise<void>
  /** Incidents no parent has acknowledged. Unknown (null) until the first successful read. */
  openCount: number | null
}

const SosContext = createContext<SosApi | null>(null)

export function useSos(): SosApi {
  const value = useContext(SosContext)
  if (!value) throw new Error('useSos outside SosProvider')
  return value
}

const PAGE = 100

/**
 * One poller for incident data, shared by the banner, the navigation badge and the SOS and Alerts
 * pages. Two reads per poll: the most recent incidents, and *all* open ones, so an open SOS that is
 * older than the newest hundred still counts (audit F-03). A failed read keeps the last data and is
 * reported, never silently treated as "no incidents".
 */
export function SosProvider({ children }: { children: ReactNode }) {
  const { api } = useAuth()
  const { state, reload } = useAsync(
    async (): Promise<SosData> => {
      const [recent, open] = await Promise.all([api.sosIncidents({ limit: PAGE }), api.sosIncidents({ status: 'open', limit: PAGE })])
      const byId = new Map<string, Incident>()
      for (const i of [...open.incidents, ...recent.incidents]) byId.set(i.incident_id, i)
      const incidents = [...byId.values()].sort((a, b) => Date.parse(b.received_at) - Date.parse(a.received_at))
      return {
        incidents,
        totalCount: recent.total_count,
        truncated: recent.has_more,
        // Trust the server's count when it has more open incidents than one page; otherwise count the page.
        openCount: open.has_more ? open.total_count : incidents.filter((i) => i.status === 'open').length,
      }
    },
    [api],
    config.sosRefreshMs,
  )
  const openCount = state.data ? state.data.openCount : null
  const value = useMemo(() => ({ state, reload, openCount }), [state, reload, openCount])
  return <SosContext.Provider value={value}>{children}</SosContext.Provider>
}
