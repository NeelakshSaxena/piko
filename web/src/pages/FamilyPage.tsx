import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useFamily } from '../auth/FamilyContext'
import { Avatar, Card, Chip, ErrorState, Loading, PageTitle, StatusBadge } from '../components/ui'
import { ageSeconds, formatAge, formatDateTime } from '../lib/format'
import { useNow } from '../lib/useAsync'
import { InviteSection, PairingSection } from './ManageSections'

const ROLE_LABEL: Record<string, string> = { parent: 'Parent', family_admin: 'Family admin', guardian: 'Guardian', child: 'Child' }

export function FamilyPage() {
  const { state, canManage } = useAuth()
  const { family, reload, children } = useFamily()
  const now = useNow(15_000)
  if (state.status !== 'authenticated') return null
  const adults = (family.data?.members ?? []).filter((m) => m.role !== 'child')

  return (
    <>
      <PageTitle>Family Members</PageTitle>
      {family.status === 'loading' && !family.data && <Loading label="Loading your family…" />}
      {family.status === 'error' && <ErrorState error={family.error} what="your family" onRetry={() => void reload()} />}

      {family.data && (
        <>
          <section aria-labelledby="adults-h" className="stack">
            <h2 id="adults-h" className="h2">
              Adults
            </h2>
            <Card>
              <ul className="plain list">
                {adults.map((m) => (
                  <li key={m.id} className="row between">
                    <span className="row">
                      <Avatar name={m.name ?? m.email ?? '?'} tone="sky" />
                      <span>
                        <strong>{m.name ?? m.email ?? 'Member'}</strong>
                        {m.name && m.email && <span className="muted small"> · {m.email}</span>}
                        <span className="muted small"> · joined {formatDateTime(m.joined_at)}</span>
                      </span>
                    </span>
                    <span className="row">
                      <Chip tone={m.role === 'guardian' ? 'sky' : 'lavender'}>{ROLE_LABEL[m.role] ?? m.role}</Chip>
                      {m.status !== 'active' && <Chip tone="amber">{m.status}</Chip>}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </section>

          <section aria-labelledby="kids-h" className="stack">
            <h2 id="kids-h" className="h2">
              Children and their phones
            </h2>
            {children.length === 0 ? (
              <Card>
                <p className="muted">No phone is linked yet.{canManage ? ' Create a pairing code below.' : ' A parent can link one.'}</p>
              </Card>
            ) : (
              <Card>
                <ul className="plain list">
                  {children.map(({ member, devices }) => (
                    <li key={member.id} className="row between">
                      <span className="row">
                        <Avatar name={member.name ?? '?'} />
                        <strong>{member.name ?? 'Unnamed phone'}</strong>
                      </span>
                      <span className="row">
                        {devices.length === 0 && <Chip tone="grey">No phone linked</Chip>}
                        {devices.map((d) => (
                          <span key={d.id} className="row">
                            <StatusBadge status={d.last_seen && (ageSeconds(d.last_seen, now) ?? Infinity) <= 300 ? 'online' : d.last_seen ? 'offline' : 'unknown'} />
                            <span className="muted small">{d.last_seen ? `last contact ${formatAge(ageSeconds(d.last_seen, now))}` : 'never contacted'}</span>
                            <Link className="btn btn-soft" to={`/health?device=${d.id}`}>
                              Device health
                            </Link>
                          </span>
                        ))}
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </section>

          {canManage ? (
            <div className="two-col even">
              <PairingSection />
              <InviteSection familyId={state.family.id} />
            </div>
          ) : (
            <Card tone="sky">
              <h2 className="h2">View-only access</h2>
              <p>Your role can see the family but cannot link phones or invite people. Ask a parent.</p>
            </Card>
          )}
        </>
      )}
    </>
  )
}
