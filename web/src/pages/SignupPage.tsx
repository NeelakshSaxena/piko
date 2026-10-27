import { Link } from 'react-router-dom'
import { CouponBox } from '../components/CouponBox'
import { Card, PageTitle } from '../components/ui'
import { config } from '../config'

/**
 * There is no self-service signup yet: families are created by the operator and adults join by invitation.
 * This page says so and shows the real ways in, instead of a form that would go nowhere.
 */
export function SignupPage() {
  return (
    <main id="main" className="narrow">
      <PageTitle>Create a Piko account</PageTitle>
      <p className="muted">Online account creation is not open yet. These are the ways to get started today.</p>

      <Card tone="sky">
        <h2 className="h2">Were you invited to a family?</h2>
        <p>Use the invite code a parent gave you to create your own login.</p>
        <Link className="btn btn-primary" to="/join">
          Join with an invite code
        </Link>
      </Card>

      <Card tone="mint">
        <h2 className="h2">Request access to Piko Hosted</h2>
        <p>
          Hosted families are set up by hand for now. Email the operator with your family name and the email address you want to sign in with; you
          will get a reply with next steps. Read the <Link to="/privacy">privacy notice</Link> first.
        </p>
        <a className="btn btn-primary" href={`mailto:${config.contactEmail}?subject=${encodeURIComponent('Piko Hosted access request')}`}>
          Email {config.contactEmail}
        </a>
      </Card>

      <Card>
        <h2 className="h2">Run Piko yourself (free)</h2>
        <p>You host the server and keep the data. The guide walks through install, first parent account, HTTPS and backups.</p>
        <a className="btn btn-soft" href="/#self-host">
          How to deploy it yourself
        </a>
      </Card>

      <Card>
        <h2 className="h2">Piko Hosted: ₹300 per family per month</h2>
        <p>The operator runs the server for you. Signup and billing are not open yet. If you have an early-bird code, enter it here.</p>
        <CouponBox id="piko-signup-coupon" />
      </Card>

      <p className="muted">
        Already have an account? <Link to="/login">Sign in</Link>.
      </p>
    </main>
  )
}
