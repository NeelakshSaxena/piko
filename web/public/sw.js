/* Piko service worker: shows a privacy-safe notification when the server pushes, and opens the right
 * page when it is clicked. It holds no data and makes no network requests. The push payload carries only a
 * type and an id, never a name, a message or a position, so nothing private can appear on a lock screen.
 * Plain JavaScript on purpose: this file is served as-is, outside the build. */

const TEXT = {
  sos_created: { title: 'SOS alert', body: 'A child has raised an SOS. Open Piko now.', urgent: true },
  sos_update: { title: 'SOS update', body: 'An SOS has changed. Open Piko.', urgent: false },
  message: { title: 'New message', body: 'There is a new message from a child. Open Piko to read it.', urgent: false },
}
const FALLBACK = { title: 'Piko', body: 'Open Piko to see an update.', urgent: false }

function parse(event) {
  try {
    const data = event.data ? event.data.json() : null
    if (data && typeof data.type === 'string' && typeof data.id === 'string') return { type: data.type, id: data.id }
  } catch (_) {
    /* a malformed payload still gets a generic notification below */
  }
  return null
}

function pageFor(type, id) {
  if (type === 'sos_created' || type === 'sos_update') return '/sos?incident=' + encodeURIComponent(id)
  if (type === 'message') return '/messages'
  return '/alerts'
}

self.addEventListener('push', (event) => {
  const info = parse(event)
  const text = (info && TEXT[info.type]) || FALLBACK
  event.waitUntil(
    self.registration.showNotification(text.title, {
      body: text.body,
      // One notification per event: a repeated push for the same id replaces it instead of stacking.
      tag: info ? info.type + ':' + info.id : 'piko',
      renotify: false,
      requireInteraction: text.urgent,
      icon: '/icon-192.png',
      badge: '/favicon.png',
      data: { url: info ? pageFor(info.type, info.id) : '/alerts' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = (event.notification.data && event.notification.data.url) || '/alerts'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin && 'focus' in client) {
          client.navigate(target)
          return client.focus()
        }
      }
      return self.clients.openWindow(target)
    }),
  )
})
