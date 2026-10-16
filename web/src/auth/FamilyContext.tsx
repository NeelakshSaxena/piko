import { createContext, useContext, type ReactNode } from 'react'
import type { FamilyDetail, FamilyDevice, Member } from '../api/types'
import { config } from '../config'
import { useAsync, type AsyncState } from '../lib/useAsync'
import { useAuth } from './AuthContext'

interface FamilyApi {
  family: AsyncState<FamilyDetail>
  reload: () => Promise<void>
  /** Members who share a location (children), each with the devices they own. */
  children: { member: Member; devices: FamilyDevice[] }[]
}

const FamilyContext = createContext<FamilyApi | null>(null)

export function useFamily(): FamilyApi {
  const value = useContext(FamilyContext)
  if (!value) throw new Error('useFamily outside FamilyProvider')
  return value
}

export function FamilyProvider({ familyId, children }: { familyId: string; children: ReactNode }) {
  const { api } = useAuth()
  const { state, reload } = useAsync(() => api.family(familyId), [api, familyId], config.refreshMs)
  const detail = state.data
  const kids = (detail?.members ?? [])
    .filter((m) => m.role === 'child' && m.status === 'active')
    .map((member) => ({
      member,
      devices: (detail?.devices ?? []).filter((d) => d.owner_member_id === member.id && d.status !== 'revoked'),
    }))
  return <FamilyContext.Provider value={{ family: state, reload, children: kids }}>{children}</FamilyContext.Provider>
}
