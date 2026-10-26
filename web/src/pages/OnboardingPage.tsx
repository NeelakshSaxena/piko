import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useFamily } from '../auth/FamilyContext'
import { PushSetup } from '../components/PushSetup'
import { Card, Chip, ErrorState, Loading, PageTitle } from '../components/ui'
import { InviteSection, PairingSection } from './ManageSections'

function StepHeading({ n, id, done, children }: { n: number; id: string; done?: boolean; children: string }) {
  return (
    <div className="row between">
      <h2 id={id} className="h2">
        Step {n}: {children}
      </h2>
      {done !== undefined && <Chip tone={done ? 'mint' : 'grey'}>{done ? 'Done' : 'To do'}</Chip>}
    </div>
  )
}

/**
 * First-run guide for a parent. Progress is read from the server (a phone counts as linked only once the
 * family record shows one), never from a local flag, so it cannot claim a step is finished that is not.
 */
export function OnboardingPage() {
  const { state, canManage } = useAuth()
  const { family, reload, children } = useFamily()
  if (state.status !== 'authenticated') return null
  if (!canManage) return <Navigate to="/" replace />

  const linked = children.some((c) => c.devices.length > 0)

  return (
    <>
      <PageTitle>Welcome to Piko</PageTitle>
      <p className="muted">
        {family.data?.name ?? state.family.name}: four short steps to start sharing safely. You can come back to this guide any time from the
        overview.
      </p>
      {family.status === 'loading' && !family.data && <Loading label="Loading your family…" />}
      {family.status === 'error' && <ErrorState error={family.error} what="your family" onRetry={() => void reload()} />}

      {family.data && (
        <>
          <section aria-labelledby="ob-1" className="stack">
            <StepHeading n={1} id="ob-1">
              What is shared, and with whom
            </StepHeading>
            <Card tone="sky">
              <ul className="plain stack tight">
                <li>A linked phone shares its location, battery and network state with the adults in this family.</li>
                <li>
                  The child's phone shows that sharing is on, and the child has to agree on the phone when linking. Piko is not for tracking
                  anyone in secret; talk to your child before you link a phone.
                </li>
                <li>Every time an adult looks at a location, the family's audit log records who and when (never the coordinates).</li>
                <li>
                  A location is shown with its age. Anything older than a few minutes is marked as not current. Piko is not an emergency service
                  and does not call anyone.
                </li>
              </ul>
            </Card>
          </section>

          <section aria-labelledby="ob-2" className="stack">
            <StepHeading n={2} id="ob-2" done={linked}>
              Link a child's phone
            </StepHeading>
            {linked ? (
              <Card tone="mint">
                <p>A phone is linked. It will report once the app is open and has a connection.</p>
              </Card>
            ) : (
              <p className="muted">This page checks for the phone by itself; it turns to "Done" a few seconds after the child finishes linking.</p>
            )}
            <PairingSection />
          </section>

          <section aria-labelledby="ob-3" className="stack">
            <StepHeading n={3} id="ob-3">
              Choose how you hear about an SOS
            </StepHeading>
            <PushSetup />
          </section>

          <section aria-labelledby="ob-4" className="stack">
            <StepHeading n={4} id="ob-4">
              Invite another adult (optional)
            </StepHeading>
            <InviteSection familyId={state.family.id} />
          </section>

          <div className="row">
            <Link className="btn btn-primary" to="/">
              {linked ? 'Go to the dashboard' : 'Skip for now and go to the dashboard'}
            </Link>
          </div>
        </>
      )}
    </>
  )
}
