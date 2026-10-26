import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useFamily } from '../auth/FamilyContext'
import { PushSetup } from '../components/PushSetup'
import { Card, PageTitle } from '../components/ui'
import { config } from '../config'
import { playSound, setSoundsMuted, soundsMuted } from '../lib/sound'

/** Only facts the dashboard actually knows. Nothing here changes server data. */
export function SettingsPage() {
  const { state, signOut } = useAuth()
  const { family } = useFamily()
  const [muted, setMuted] = useState(soundsMuted())
  if (state.status !== 'authenticated') return null
  return (
    <>
      <PageTitle>Settings</PageTitle>
      <div className="two-col even">
        <Card>
          <h2 className="h2">This session</h2>
          <dl className="kv">
            <div><dt>Family</dt><dd>{family.data?.name ?? state.family.name}</dd></div>
            <div><dt>Your role</dt><dd>{state.role.replace('_', ' ')}</dd></div>
            <div><dt>Server</dt><dd>{config.apiBase}</dd></div>
          </dl>
          <p className="muted small">The session ends when you close this tab or sign out. Each tab signs in separately.</p>
          <button type="button" className="btn btn-primary" onClick={() => void signOut()}>
            Sign out
          </button>
        </Card>
        <Card>
          <h2 className="h2">Privacy &amp; data</h2>
          <ul className="plain stack tight">
            <li>Each time someone looks at a location or its history, the family's audit log records who and when (never the coordinates).</li>
            <li>Location history is kept for the family's retention period (30 days unless it was changed on the server).</li>
            <li>
              Map tiles: {config.tileUrl ? 'loaded from the configured tile server, which can see roughly which area is viewed.' : 'switched off by the operator; positions are shown as markers only.'}
            </li>
            <li>Password changes and retention changes are not available in this version.</li>
          </ul>
        </Card>
      </div>
      <Card>
        <h2 className="h2">Alert sounds</h2>
        <p className="muted">
          While this dashboard is open it plays a sound for a new SOS and for a new message from a phone. Your browser may stay silent until
          you have clicked somewhere on the page. Sounds from browser notifications are chosen by your system.
        </p>
        <label className="row">
          <input
            type="checkbox"
            checked={!muted}
            onChange={(e) => {
              setMuted(!e.target.checked)
              setSoundsMuted(!e.target.checked)
            }}
          />
          Play alert sounds on this browser
        </label>
        <button type="button" className="btn btn-soft" onClick={() => playSound('sos')}>
          Test the SOS sound
        </button>
      </Card>
      <PushSetup />
    </>
  )
}
