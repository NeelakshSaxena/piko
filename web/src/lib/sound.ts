/**
 * Alert sounds for the open dashboard. Browsers refuse to play audio before the person has interacted
 * with the page, so a refused play is expected and silent; the visible banner and badge remain the
 * source of truth. A browser's own push notifications use the operating system's sound, which a page
 * cannot choose. The preference is per browser and is read defensively (storage can be blocked).
 */
export type SoundName = 'sos' | 'general'

const FILES: Record<SoundName, string> = {
  sos: '/sounds/sos_notification.mp3',
  general: '/sounds/general_notification.mp3',
}
const KEY = 'piko.sounds.muted'

export function soundsMuted(): boolean {
  try {
    return window.localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function setSoundsMuted(muted: boolean): void {
  try {
    window.localStorage.setItem(KEY, muted ? '1' : '0')
  } catch {
    /* the choice just does not persist */
  }
}

export function playSound(name: SoundName): void {
  if (soundsMuted() || typeof Audio === 'undefined') return
  try {
    const audio = new Audio(FILES[name])
    audio.volume = name === 'sos' ? 1 : 0.6
    const started = audio.play()
    if (started) started.catch(() => undefined) // autoplay not allowed yet, or no audio device
  } catch {
    /* jsdom and some embedded browsers have no audio */
  }
}
