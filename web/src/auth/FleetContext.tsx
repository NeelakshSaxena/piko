import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { DeviceDetail, FamilyDevice, Member, MemberLocation } from '../api/types'
import { config } from '../config'
import { useAuth } from './AuthContext'
import { useFamily } from './FamilyContext'

/** Everything the dashboard knows about one child, read once per refresh and shared by every page. */
export interface FleetEntry {
  member: Member
  device: FamilyDevice | undefined
  detail: DeviceDetail | null
  location: MemberLocation | null
  /** Set when the latest refresh failed; the previous values above are then the last known ones. */
  error: ApiError | null
}

interface FleetApi {
  entries: FleetEntry[]
  loading: boolean
  /** Epoch ms of the last refresh that fully succeeded; null before the first one. */
  lastLoadedAt: number | null
  failing: boolean
  reload: () => Promise<void>
}

const FleetContext = createContext<FleetApi | null>(null)

export function useFleet(): FleetApi {
  const value = useContext(FleetContext)
  if (!value) throw new Error('useFleet outside FleetProvider')
  return value
}

function asApiError(reason: unknown): ApiError {
  return reason instanceof ApiError ? reason : new ApiError(0, 'UNKNOWN', 'Something went wrong.')
}

export function FleetProvider({ children: content }: { children: ReactNode }) {
  const { api } = useAuth()
  const { children: kids, family } = useFamily()
  const [entries, setEntries] = useState<FleetEntry[]>([])
  const [lastLoadedAt, setLastLoadedAt] = useState<number | null>(null)
  const [failing, setFailing] = useState(false)
  const [loading, setLoading] = useState(true)
  const alive = useRef(true)
  const kidsRef = useRef(kids)
  kidsRef.current = kids
  // Re-read when the set of children changes, not on every parent render.
  const signature = kids.map((k) => `${k.member.id}:${k.devices.map((d) => d.id).join(',')}`).join('|')

  const reload = useCallback(async () => {
    const current = kidsRef.current
    const next = await Promise.all(
      current.map(async ({ member, devices }): Promise<FleetEntry> => {
        const device = devices[0]
        const [loc, det] = await Promise.allSettled([
          api.memberLocation(member.id),
          device ? api.device(device.id) : Promise.resolve(null),
        ])
        const error = loc.status === 'rejected' ? asApiError(loc.reason) : det.status === 'rejected' ? asApiError(det.reason) : null
        return {
          member,
          device,
          location: loc.status === 'fulfilled' ? loc.value : null,
          detail: det.status === 'fulfilled' ? det.value : null,
          error,
        }
      }),
    )
    if (!alive.current) return
    setEntries((previous) =>
      next.map((entry) => {
        const old = previous.find((p) => p.member.id === entry.member.id)
        // Keep the last known values when a refresh fails, and say that it failed.
        return entry.error && old ? { ...entry, location: entry.location ?? old.location, detail: entry.detail ?? old.detail } : entry
      }),
    )
    const bad = next.some((e) => e.error)
    setFailing(bad)
    if (!bad) setLastLoadedAt(Date.now())
    setLoading(false)
  }, [api])

  useEffect(() => {
    alive.current = true
    if (family.status === 'loading' && !family.data) return
    setLoading(true)
    void reload()
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void reload()
    }, config.refreshMs)
    return () => {
      alive.current = false
      clearInterval(timer)
    }
  }, [signature, reload, family.status])

  const value = useMemo(() => ({ entries, loading, lastLoadedAt, failing, reload }), [entries, loading, lastLoadedAt, failing, reload])
  return <FleetContext.Provider value={value}>{content}</FleetContext.Provider>
}
