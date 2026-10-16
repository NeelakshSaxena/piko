import { useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Card, Loading, PageTitle } from '../components/ui'

const NOTICES = {
  expired: 'Your session ended. Please sign in again.',
  'signed-out': 'You are signed out.',
  unreachable: 'The Piko server could not be reached. Check your connection and sign in again.',
} as const

export function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Something went wrong. Please try again.'
  if (error.code === 'NETWORK') return 'Cannot reach the Piko server. Check your connection.'
  if (error.code === 'RATE_LIMIT') {
    return `Too many attempts. Wait ${error.retryAfterSeconds ?? 60} seconds and try again.`
  }
  if (error.status === 401 || error.code === 'AUTH_INVALID') return 'That email and password do not match.'
  return error.message
}

export function LoginPage() {
  const { state, signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (state.status === 'loading') return <Loading label="Checking your session…" />
  if (state.status === 'authenticated') return <Navigate to="/" replace />

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(email.trim(), password)
    } catch (e) {
      setError(messageFor(e))
      setBusy(false)
    }
  }

  const notice = state.notice ? NOTICES[state.notice] : null
  return (
    <main id="main" className="narrow">
      <PageTitle>Sign in to Piko</PageTitle>
      {notice && (
        <div className="banner" role="status">
          {notice}
        </div>
      )}
      <Card>
        <form onSubmit={submit} className="form" noValidate>
          <label>
            Email
            <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="btn btn-primary" disabled={busy || !email || !password}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </Card>
      <p className="muted">
        Were you invited to a family? <Link to="/join">Join with an invite code</Link>.
      </p>
    </main>
  )
}
