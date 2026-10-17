import type { ApiClient } from '../api/client'

/**
 * Browser push (W3C Web Push). The server sends a content-free message (a type and an id) to this
 * browser's push service; the service worker shows a generic notification. This is a convenience:
 * the dashboard remains the source of truth, and "accepted by the push service" is not "shown".
 */
export type PushState =
  | { kind: 'unsupported'; reason: string }
  | { kind: 'not-configured' } // the server has no VAPID key / transport
  | { kind: 'blocked' } // the person denied the browser permission
  | { kind: 'off' }
  | { kind: 'on' }

export function pushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window &&
    window.isSecureContext
  )
}

/** VAPID public keys are base64url; the Push API wants bytes. */
export function urlBase64ToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value + '='.repeat((4 - (value.length % 4)) % 4)
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
  return bytes
}

async function registration(): Promise<ServiceWorkerRegistration> {
  return navigator.serviceWorker.register('/sw.js', { scope: '/' })
}

export async function pushState(api: ApiClient): Promise<PushState> {
  if (!pushSupported()) {
    return { kind: 'unsupported', reason: window.isSecureContext ? 'This browser cannot receive push messages.' : 'Push needs https (or localhost).' }
  }
  const config = await api.pushConfig()
  if (!config.web_push_enabled || !config.vapid_public_key) return { kind: 'not-configured' }
  if (Notification.permission === 'denied') return { kind: 'blocked' }
  const reg = await navigator.serviceWorker.getRegistration('/')
  const sub = reg ? await reg.pushManager.getSubscription() : null
  return sub && Notification.permission === 'granted' ? { kind: 'on' } : { kind: 'off' }
}

/** Must be called from a click: the browser only shows its permission prompt for a user gesture. */
export async function enablePush(api: ApiClient): Promise<PushState> {
  if (!pushSupported()) return pushState(api)
  const config = await api.pushConfig()
  if (!config.web_push_enabled || !config.vapid_public_key) return { kind: 'not-configured' }
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') return { kind: permission === 'denied' ? 'blocked' : 'off' }
  const reg = await registration()
  await navigator.serviceWorker.ready
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToBytes(config.vapid_public_key) }))
  const json = sub.toJSON()
  if (!json.endpoint || !json.keys?.p256dh || !json.keys.auth) {
    await sub.unsubscribe()
    return { kind: 'off' }
  }
  await api.registerWebPush({ endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } })
  return { kind: 'on' }
}

/** Turns push off for this browser: tells the server first, then drops the browser subscription. */
export async function disablePush(api: ApiClient): Promise<void> {
  if (!pushSupported()) return
  const reg = await navigator.serviceWorker.getRegistration('/')
  const sub = reg ? await reg.pushManager.getSubscription() : null
  if (!sub) return
  try {
    await api.removeWebPush(sub.endpoint)
  } finally {
    await sub.unsubscribe()
  }
}
