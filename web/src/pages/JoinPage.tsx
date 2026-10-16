import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Card, PageTitle } from '../components/ui'
import { messageFor } from './LoginPage'

const MIN_PASSWORD = 12

export function JoinPage() {
  const { api } = useAuth()
  const [code, setCode] = useState('')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (password.length < MIN_PASSWORD) {
      setError(`Choose a password of at least ${MIN_PASSWORD} characters.`)
      return
    }
    setBusy(true)
    try {
      await api.acceptInvite(code.trim(), email.trim(), password, name.trim())
      setDone(true)
    } catch (e) {
      // The server answers every refusal identically on purpose, so the page cannot say which part was wrong.
      setError(
        e instanceof ApiError && e.status === 401
          ? 'That invite code and email do not match, or the invitation has expired or was already used. Ask the person who invited you for a new code.'
          : messageFor(e),
      )
      setBusy(false)
    }
  }

  if (done) {
    return (
      <main id="main" className="narrow">
        <PageTitle>You have joined the family</PageTitle>
        <Card tone="mint">
          <p>Your account is ready.</p>
          <Link className="btn btn-primary" to="/login">
            Sign in
          </Link>
        </Card>
      </main>
    )
  }

  return (
    <main id="main" className="narrow">
      <PageTitle>Join a family</PageTitle>
      <p className="muted">Enter the invite code you were given and the email address it was made for.</p>
      <Card>
        <form onSubmit={submit} className="form" noValidate>
          <label>
            Invite code
            <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="ABC-DEF-GHI" autoComplete="off" required />
          </label>
          <label>
            Email
            <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label>
            Your name (optional)
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          </label>
          <label>
            New password
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby="pw-help"
              required
            />
            <span id="pw-help" className="muted small">
              At least {MIN_PASSWORD} characters.
            </span>
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="btn btn-primary" disabled={busy || !code || !email || !password}>
            {busy ? 'Creating account…' : 'Create my account'}
          </button>
        </form>
      </Card>
      <p className="muted">
        Already have an account? <Link to="/login">Sign in</Link>.
      </p>
    </main>
  )
}
