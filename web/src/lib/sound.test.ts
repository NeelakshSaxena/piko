import { afterEach, describe, expect, it, vi } from 'vitest'
import { playSound, setSoundsMuted, soundsMuted } from './sound'

afterEach(() => {
  window.localStorage.clear()
  vi.unstubAllGlobals()
})

describe('alert sounds', () => {
  it('plays the named file and survives a browser that refuses autoplay', async () => {
    const play = vi.fn(() => Promise.reject(new Error('NotAllowedError')))
    const made: string[] = []
    vi.stubGlobal('Audio', function (this: unknown, src: string) {
      made.push(src)
      return { play, volume: 0 }
    })
    playSound('sos')
    playSound('general')
    await Promise.resolve()
    expect(made).toEqual(['/sounds/sos_notification.mp3', '/sounds/general_notification.mp3'])
    expect(play).toHaveBeenCalledTimes(2)
  })

  it('is silent when muted, and the choice is remembered', () => {
    const ctor = vi.fn()
    vi.stubGlobal('Audio', ctor)
    setSoundsMuted(true)
    expect(soundsMuted()).toBe(true)
    playSound('sos')
    expect(ctor).not.toHaveBeenCalled()
    setSoundsMuted(false)
    expect(soundsMuted()).toBe(false)
  })
})
