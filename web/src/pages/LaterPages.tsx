import { NotAvailable } from '../components/ui'

/**
 * Parts of the designs whose backend does not exist yet. They are real pages with real navigation,
 * and they say plainly that nothing is being simulated. (SOS and messaging are Phase 6.)
 */
export function SosPage() {
  return (
    <NotAvailable
      title="SOS Emergency Centre"
      intro="This version of Piko cannot send, receive or show SOS alerts. The Android app has no SOS button yet, so an emergency would never appear here."
    >
      <ul className="plain stack tight">
        <li>When it exists, active, acknowledged and resolved incidents will be listed here, each marked as queued, delivered or acknowledged, never as delivered before the server confirms it.</li>
        <li>
          <strong>In an emergency, call your local emergency number. Do not rely on Piko to call for help.</strong>
        </li>
      </ul>
    </NotAvailable>
  )
}

export function MessagesPage() {
  return <NotAvailable title="Messages" intro="Family messaging and check-in requests are planned for a later version. There is nothing to send or read here yet." />
}

export function AlertsPage() {
  return (
    <NotAvailable
      title="Alerts"
      intro="Safe-zone and low-battery alerts are planned for a later version. Piko does not notify you about anything yet, so keep checking the Overview and Live Map pages."
    />
  )
}
