import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import type { InvitableRole, InviteResult, PairingCode } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Card, ErrorState } from '../components/ui'
import { formatDateTime } from '../lib/format'
import { useNow } from '../lib/useAsync'

function asError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', 'Something went wrong.')
}

function Countdown({ expiresAt }: { expiresAt: string }) {
  const now = useNow(1000)
  const left = Math.max(0, Math.floor((Date.parse(expiresAt) - now) / 1000))
  if (left === 0) return <strong>This code has expired. Create a new one.</strong>
  const mm = String(Math.floor(left / 60)).padStart(2, '0')
  const ss = String(left % 60).padStart(2, '0')
  return (
    <span>
      Expires in{' '}
      <strong>
        {mm}:{ss}
      </strong>
    </span>
  )
}

export function PairingSection() {
  const { api } = useAuth()
  const [code, setCode] = useState<PairingCode | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  async function create() {
    setBusy(true)
    setError(null)
    try {
      setCode(await api.createPairingCode())
    } catch (e) {
      setError(asError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h2 className="h2">Link a child's phone</h2>
      <p className="muted">
        Install the Piko app on the phone, choose "Continue as Child", then type this code. Creating a new code cancels the previous one.
      </p>
      {error && <ErrorState error={error} what="a code" />}
      {code && (
        <div className="secret" aria-live="polite">
          <p className="code" aria-label={`Pairing code ${code.pairing_code.split('').join(' ')}`}>
            {code.pairing_code}
          </p>
          <p>
            <Countdown expiresAt={code.expires_at} /> · works once · valid until {formatDateTime(code.expires_at)}
          </p>
          <p className="muted small">This code is shown only now. It cannot be looked up later.</p>
        </div>
      )}
      <button type="button" className="btn btn-primary" onClick={() => void create()} disabled={busy}>
        {busy ? 'Creating…' : code ? 'Create a new code' : 'Create pairing code'}
      </button>
    </Card>
  )
}

export function InviteSection({ familyId }: { familyId: string }) {
  const { api } = useAuth()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<InvitableRole>('guardian')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [result, setResult] = useState<InviteResult | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setResult(await api.invite(familyId, email.trim(), role))
      setEmail('')
    } catch (e) {
      setError(asError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h2 className="h2">Invite another adult</h2>
      <p className="muted">
        Piko does not send email. You get a one-time code to give them yourself; it works for 7 days and only with the email address you enter.
      </p>
      <form onSubmit={submit} className="form" noValidate>
        <label>
          Their email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="off" />
        </label>
        <label>
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as InvitableRole)}>
            <option value="guardian">Guardian: can see the family and locations, cannot change anything</option>
            <option value="parent">Parent: full access</option>
            <option value="family_admin">Family admin: full access</option>
          </select>
        </label>
        {error && <ErrorState error={error} what="the invitation" />}
        <button type="submit" className="btn btn-primary" disabled={busy || !email}>
          {busy ? 'Creating…' : 'Create invite code'}
        </button>
      </form>
      {result && (
        <div className="secret" aria-live="polite">
          <p className="code" aria-label={`Invite code ${result.invite_code.split('').join(' ')}`}>
            {result.invite_code}
          </p>
          <p>
            For <strong>{result.email}</strong> as {result.role.replace('_', ' ')} · expires {formatDateTime(result.expires_at)}
          </p>
          <p className="muted small">Shown only now. They sign up at the "Join with an invite code" link on the sign-in page.</p>
        </div>
      )}
    </Card>
  )
}
