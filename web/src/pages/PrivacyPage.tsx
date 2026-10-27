import { Link } from 'react-router-dom'
import { Card, PageTitle } from '../components/ui'
import { config } from '../config'

/**
 * Plain-language privacy notice. Every statement here describes what the software does today
 * (docs/DATA_MODEL.md, retention.py, the audit log); change this page when the behaviour changes.
 * It is a draft for the operator to review with a lawyer before real families rely on it.
 */
export function PrivacyPage() {
  const mail = `mailto:${config.contactEmail}`
  return (
    <main id="main" className="narrow">
      <PageTitle>Privacy notice</PageTitle>
      <p className="muted">Last updated 27 October 2026. Draft: not yet reviewed by a lawyer.</p>

      <Card>
        <h2 className="h2">Who runs this</h2>
        <p>
          This Piko service is run by its operator, an individual, who decides why and how your family&apos;s data is used. Contact:{' '}
          <a href={mail}>{config.contactEmail}</a>. If you run Piko on your own server, you are the operator and this notice describes the
          software, not your server.
        </p>
      </Card>

      <Card>
        <h2 className="h2">What Piko collects</h2>
        <ul className="plain stack tight">
          <li>
            <strong>Account:</strong> an adult&apos;s email address, optional name, and a salted hash of the password (never the password itself).
          </li>
          <li>
            <strong>From a child&apos;s phone, only while sharing is on:</strong> location with its accuracy and when it was taken, battery level and
            charging state, network type, and the phone&apos;s name, model and Android version.
          </li>
          <li>
            <strong>SOS and messages:</strong> SOS events (time, optional note, last known position) and the text messages parents and the child send
            through Piko.
          </li>
          <li>
            <strong>Security records:</strong> a log of who signed in and who looked at a location or conversation, and when. The log never contains
            coordinates or message text.
          </li>
          <li>
            <strong>Notifications:</strong> if you turn them on, the address your browser or phone gives the push service so it can be alerted.
          </li>
        </ul>
        <p>
          Piko does not read a phone&apos;s contacts, text messages, photos, apps or microphone, and it has no advertising or analytics trackers.
        </p>
      </Card>

      <Card>
        <h2 className="h2">Children</h2>
        <p>
          A phone is linked only when a parent creates a one-time code and the child agrees on the phone, after seeing what will be shared. A
          notification stays visible on the phone while location is shared, and the child can stop sharing at any time. Sharing a child&apos;s
          location needs the consent of a parent or lawful guardian and, where the law requires it, verifiable parental consent. Parents should talk
          to their child before linking a phone. Piko is not designed to track anyone in secret.
        </p>
      </Card>

      <Card>
        <h2 className="h2">Who can see it</h2>
        <p>
          Only adults in the same family (parents, family admins and view-only guardians) can see the family&apos;s locations, status, SOS events
          and messages. A child sees their own phone&apos;s information. Every look at a location is recorded in the security log. We do not sell
          data, build advertising profiles, or share it with anyone for their own purposes.
        </p>
      </Card>

      <Card>
        <h2 className="h2">Services that touch the data</h2>
        <ul className="plain stack tight">
          <li>The operator&apos;s hosting provider and database provider store the data on its behalf.</li>
          <li>
            Push services (your browser vendor&apos;s, and Google&apos;s Firebase Cloud Messaging for the phone app) deliver alerts. A notification
            says only that something happened; it never contains names, message text or a position.
          </li>
          <li>
            The live map loads map tiles from OpenStreetMap, which can see roughly which area is being viewed. The operator can switch this off or
            use another tile server.
          </li>
        </ul>
      </Card>

      <Card>
        <h2 className="h2">How long it is kept</h2>
        <ul className="plain stack tight">
          <li>Location, battery and network history: 30 days by default, then deleted.</li>
          <li>Messages: 90 days. Security log: 365 days. Delivered notification records: 30 days.</li>
          <li>SOS events are safety records and are kept until the family is deleted.</li>
          <li>Backups may keep older data for as long as the backup exists.</li>
        </ul>
        <p>Deletion runs as a scheduled job. Piko is not an emergency service and does not call anyone.</p>
      </Card>

      <Card>
        <h2 className="h2">Your choices</h2>
        <p>
          You can ask to see, correct or delete your family&apos;s data, remove a phone, or close the family by writing to{' '}
          <a href={mail}>{config.contactEmail}</a>. Deleting data on request is currently done by hand by the operator. A parent can also unlink a
          phone from the Family Members page, and a child can stop sharing in the app.
        </p>
      </Card>

      <p className="muted">
        <Link to="/">Back to home</Link> · <Link to="/signup">Create an account</Link>
      </p>
    </main>
  )
}
