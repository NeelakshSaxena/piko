import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiClient, ApiError } from '../api/client'
import type { FamilySummary, Role } from '../api/types'
import { disablePush } from '../lib/push'

export type AuthState =
  | { status: 'loading' }
  | { status: 'anonymous'; notice?: 'expired' | 'signed-out' | 'unreachable' }
  | { status: 'authenticated'; family: FamilySummary; role: Role }

interface AuthApi {
  state: AuthState
  api: ApiClient
  signIn(email: string, password: string): Promise<void>
  signOut(): Promise<void>
  /** UI hint only. The server enforces every permission; this just hides buttons that would be refused. */
  canManage: boolean
}

const AuthContext = createContext<AuthApi | null>(null)

export function useAuth(): AuthApi {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth outside AuthProvider')
  return value
}

const MANAGE_ROLES: Role[] = ['parent', 'family_admin']

async function loadFamily(api: ApiClient): Promise<AuthState> {
  const families = await api.families()
  const family = families[0]
  // A session whose account has no viewable family is treated as not signed in.
  return family ? { status: 'authenticated', family, role: family.my_role } : { status: 'anonymous' }
}

export function AuthProvider({ api, children }: { api: ApiClient; children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' })

  useEffect(() => {
    api.onSessionLost = () => setState({ status: 'anonymous', notice: 'expired' })
    let cancelled = false
    void (async () => {
      try {
        if (!(await api.restore())) {
          if (!cancelled) setState({ status: 'anonymous' })
          return
        }
        const next = await loadFamily(api)
        if (!cancelled) setState(next)
      } catch (error) {
        if (cancelled) return
        const unreachable = error instanceof ApiError && error.code === 'NETWORK'
        setState({ status: 'anonymous', notice: unreachable ? 'unreachable' : undefined })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [api])

  const signIn = useCallback(
    async (email: string, password: string) => {
      await api.login(email, password)
      setState(await loadFamily(api))
    },
    [api],
  )

  const signOut = useCallback(async () => {
    // Stop pushes to this browser before the session ends: afterwards the server could not authorise it.
    try {
      await disablePush(api)
    } catch {
      /* best effort: a stale subscription is also dropped when the push service reports it gone */
    }
    await api.logout()
    setState({ status: 'anonymous', notice: 'signed-out' })
  }, [api])

  const value = useMemo<AuthApi>(
    () => ({
      state,
      api,
      signIn,
      signOut,
      canManage: state.status === 'authenticated' && MANAGE_ROLES.includes(state.role),
    }),
    [state, api, signIn, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
