import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { ChatMessage } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useFamily } from '../auth/FamilyContext'
import { Card, Chip, Empty, ErrorState, Loading, PageTitle } from '../components/ui'
import { formatDateTime, formatDuration } from '../lib/format'
import { newId } from '../lib/newId'
import { playSound } from '../lib/sound'
import { useAsync } from '../lib/useAsync'

const MAX_BODY = 500
const LATE_SECONDS = 5 * 60

/**
 * A message not yet confirmed stored by the server. It lives in memory only (message text is never
 * written to browser storage) and keeps its id, so a retry cannot create a second message.
 */
interface Pending {
  id: string
  deviceId: string
  body: string
  sentAt: string
  state: 'sending' | 'failed'
  reason?: string
}

function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError(0, 'UNKNOWN', 'Something went wrong.')
}

function failureText(error: ApiError): string {
  if (error.code === 'NETWORK') return 'Could not reach the Piko server. The message was not confirmed as sent.'
  if (error.denied) return 'The server did not allow you to send messages.'
  if (error.code === 'RATE_LIMIT') return 'Too many messages. Wait a moment, then retry.'
  if (error.status === 400) return 'The server rejected this message.'
  return 'The server could not store this message.'
}

/** What is actually known about a message, in words that never claim more than the server recorded. */
function statusLine(m: ChatMessage): string {
  if (m.sender === 'parent') {
    return m.status === 'acknowledged'
      ? `The phone confirmed it was seen ${formatDateTime(m.acknowledged_at)}.`
      : 'Delivered to the Piko server. The phone has not confirmed seeing it.'
  }
  return m.status === 'acknowledged'
    ? `Marked as seen by a parent ${formatDateTime(m.acknowledged_at)}.`
    : 'Delivered to Piko. No parent has marked it as seen.'
}

export function MessagesPage() {
  const { api, canManage } = useAuth()
  const { children } = useFamily()
  const [params, setParams] = useSearchParams()
  const selected = children.find((c) => c.member.id === params.get('member')) ?? children[0]
  const device = selected?.devices[0]
  const childName = device?.name ?? selected?.member.name ?? 'the phone'
  const deviceId = device?.id
  const { state, reload } = useAsync(() => (deviceId ? api.messages(deviceId, { limit: 100 }) : Promise.resolve(null)), [api, deviceId], 30_000)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<Pending[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [seenError, setSeenError] = useState<{ id: string; message: string } | null>(null)

  const stored = state.data?.messages ?? []
  // A chime for a message from the phone that was not in the previous read of this conversation.
  const knownFromPhone = useRef<{ deviceId: string | undefined; ids: Set<string> } | null>(null)
  useEffect(() => {
    if (!state.data) return
    const ids = new Set(state.data.messages.filter((m) => m.sender === 'device').map((m) => m.message_id))
    const before = knownFromPhone.current
    if (before && before.deviceId === deviceId && [...ids].some((id) => !before.ids.has(id))) playSound('general')
    knownFromPhone.current = { deviceId, ids }
  }, [state.data, deviceId])
  const storedIds = new Set(stored.map((m) => m.message_id))
  const visiblePending = pending.filter((p) => p.deviceId === deviceId && !storedIds.has(p.id))
  const chronological = [...stored].reverse()

  async function transmit(p: Pending) {
    setPending((list) => list.map((x) => (x.id === p.id ? { ...x, state: 'sending', reason: undefined } : x)))
    try {
      await api.sendMessage({ messageId: p.id, deviceId: p.deviceId, body: p.body, sentAt: p.sentAt })
      setPending((list) => list.filter((x) => x.id !== p.id))
      await reload()
    } catch (error) {
      setPending((list) => list.map((x) => (x.id === p.id ? { ...x, state: 'failed', reason: failureText(toApiError(error)) } : x)))
    }
  }

  function send() {
    const body = draft.trim()
    if (!body || !deviceId) return
    const p: Pending = { id: newId(), deviceId, body, sentAt: new Date().toISOString(), state: 'sending' }
    setPending((list) => [...list, p])
    setDraft('')
    void transmit(p)
  }

  async function markSeen(m: ChatMessage) {
    setBusy(m.message_id)
    setSeenError(null)
    try {
      await api.acknowledgeMessage(m.message_id)
      await reload()
    } catch (error) {
      const err = toApiError(error)
      setSeenError({ id: m.message_id, message: err.denied ? 'The server did not allow this.' : 'Could not record that. Try again.' })
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <PageTitle>Messages</PageTitle>
      {children.length === 0 && <Empty title="No phone is linked yet">Messages are exchanged with a child's phone once it is linked from the Family page.</Empty>}
      {selected && !device && <Empty title="This child has no active phone">There is nothing to send messages to.</Empty>}
      {selected && device && (
        <>
          <Card>
            <div className="filters">
              {children.length > 1 && (
                <label>
                  Conversation with
                  <select value={selected.member.id} onChange={(e) => setParams({ member: e.target.value })}>
                    {children.map(({ member, devices }) => (
                      <option key={member.id} value={member.id}>
                        {devices[0]?.name ?? member.name ?? 'Unnamed phone'}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button type="button" className="btn btn-soft" onClick={() => void reload()}>
                Refresh
              </button>
            </div>
            <p className="muted small">
              Messages are stored on the Piko server and are not end-to-end encrypted. Parents and guardians in this family can read this
              conversation. The phone fetches them when its Piko app is open or
              while sharing is on; Piko does not push them to the phone. This is not an emergency channel.
            </p>
          </Card>

          {state.status === 'loading' && !state.data && <Loading label="Loading messages…" />}
          {state.status === 'error' && <ErrorState error={state.error} what="messages" onRetry={() => void reload()} />}
          {state.status === 'error' && state.data && (
            <p className="warn" role="status">
              Showing the last messages that loaded; newer ones may be missing.
            </p>
          )}

          {state.data && chronological.length === 0 && visiblePending.length === 0 && (
            <Empty title="No messages yet">Nothing has been sent in either direction.</Empty>
          )}

          {(chronological.length > 0 || visiblePending.length > 0) && (
            <section aria-labelledby="conv-h">
              <h2 id="conv-h" className="h2">
                Conversation with {childName}
              </h2>
              <ol className="plain stack tight chat">
                {chronological.map((m) => {
                  const late = Math.round((Date.parse(m.received_at) - Date.parse(m.sent_at)) / 1000)
                  return (
                    <li key={m.message_id} className={`bubble bubble-${m.sender}`}>
                      <div className="row between">
                        <strong>{m.sender === 'device' ? childName : 'A parent'}</strong>
                        <time className="muted small" dateTime={m.sent_at}>
                          {formatDateTime(m.sent_at)}
                        </time>
                      </div>
                      <p className="user-text">{m.body}</p>
                      <p className="muted small">{statusLine(m)}</p>
                      {late > LATE_SECONDS && <Chip tone="sky">Reached Piko {formatDuration(late)} after it was sent (saved on the phone while offline)</Chip>}
                      {m.sender === 'device' && m.status === 'delivered' && canManage && (
                        <button type="button" className="btn btn-soft" disabled={busy === m.message_id} onClick={() => void markSeen(m)}>
                          Mark as seen
                        </button>
                      )}
                      {seenError?.id === m.message_id && (
                        <p role="alert" className="error">
                          {seenError.message}
                        </p>
                      )}
                    </li>
                  )
                })}
                {visiblePending.map((p) => (
                  <li key={p.id} className="bubble bubble-parent bubble-pending">
                    <div className="row between">
                      <strong>You</strong>
                      <time className="muted small" dateTime={p.sentAt}>
                        {formatDateTime(p.sentAt)}
                      </time>
                    </div>
                    <p className="user-text">{p.body}</p>
                    {p.state === 'sending' ? (
                      <p className="muted small" role="status">
                        Sending… not yet confirmed by the server.
                      </p>
                    ) : (
                      <>
                        <p role="alert" className="error">
                          Not sent. {p.reason}
                        </p>
                        <button type="button" className="btn btn-soft" onClick={() => void transmit(p)}>
                          Retry
                        </button>
                        <p className="muted small">Retrying cannot send it twice: the server recognises this message.</p>
                      </>
                    )}
                  </li>
                ))}
              </ol>
            </section>
          )}

          {canManage ? (
            <Card>
              <form
                className="form"
                onSubmit={(e) => {
                  e.preventDefault()
                  send()
                }}
              >
                <label>
                  Message to {childName}
                  <textarea rows={3} maxLength={MAX_BODY} value={draft} onChange={(e) => setDraft(e.target.value)} />
                </label>
                <span className="muted small" aria-live="polite">
                  {draft.length}/{MAX_BODY}
                </span>
                <button type="submit" className="btn btn-primary" disabled={!draft.trim()}>
                  Send message
                </button>
              </form>
            </Card>
          ) : (
            <Card tone="sky">
              <p>Guardians can read this conversation but cannot send messages or mark them as seen.</p>
            </Card>
          )}
        </>
      )}
    </>
  )
}
