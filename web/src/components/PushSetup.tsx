import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { disablePush, enablePush, pushState, type PushState } from '../lib/push'
import { Card } from './ui'

/**
 * Lets a person choose whether this browser is told about SOS and messages when the dashboard is not
 * open. It says what a notification is and is not: it carries no names, text or positions, "accepted by
 * the push service" is not "shown", and a browser that is fully closed or offline may show it late.
 */
export function PushSetup() {
  const { api } = useAuth()
  const [state, setState] = useState<PushState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    pushState(api)
      .then((s) => alive && setState(s))
      .catch((e: unknown) => alive && setError(e instanceof ApiError && e.code === 'NETWORK' ? 'Cannot reach the Piko server to check.' : 'Could not check notification status.'))
    return () => {
      alive = false
    }
  }, [api])

  async function run(action: () => Promise<PushState | void>) {
    setBusy(true)
    setError(null)
    try {
      const next = await action()
      setState(next ?? (await pushState(api)))
    } catch {
      setError('That did not work. Nothing was changed on the server unless you see "on" below.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card tone="sky">
      <h2 className="h2">Alerts on this device</h2>
      <p>
        When switched on, this browser shows a notification when a child raises an SOS or sends a message, even if the dashboard is not open.
        The notification says only that something happened; it never includes names, message text or a position.
      </p>
      {state === null && !error && <p className="muted">Checking…</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {state?.kind === 'unsupported' && <p className="warn">{state.reason} You will only see alerts while this dashboard is open.</p>}
      {state?.kind === 'not-configured' && (
        <p className="warn">This server has no browser push set up, so alerts appear only while this dashboard is open.</p>
      )}
      {state?.kind === 'blocked' && (
        <p className="warn">Notifications are blocked for this site in your browser settings. Allow them there, then come back and switch this on.</p>
      )}
      {state?.kind === 'off' && (
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run(() => enablePush(api))}>
          Turn on alerts for this browser
        </button>
      )}
      {state?.kind === 'on' && (
        <>
          <p>
            <strong>On.</strong> A push service has been told where to reach this browser. That is not proof any single alert will be shown: a
            browser that is closed, offline, or in a battery saver can show it late or not at all.
          </p>
          <button type="button" className="btn btn-soft" disabled={busy} onClick={() => void run(async () => { await disablePush(api) })}>
            Turn off
          </button>
        </>
      )}
      <p className="muted small">Piko is not an emergency service. Keep this dashboard open when you are expecting an alert.</p>
    </Card>
  )
}
