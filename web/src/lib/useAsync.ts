import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

export type AsyncState<T> =
  | { status: 'loading'; data: T | null }
  | { status: 'ready'; data: T }
  | { status: 'error'; data: T | null; error: ApiError }

function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError(0, 'UNKNOWN', 'Something went wrong.')
}

/**
 * Loads data and optionally re-reads it on an interval while the tab is visible. Previous data is
 * kept when a refresh fails, so an outage shows "last known" values with an error, not a blank page.
 */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[], refreshMs?: number) {
  const [state, setState] = useState<AsyncState<T>>({ status: 'loading', data: null })
  const loader = useRef(load)
  loader.current = load
  const alive = useRef(true)

  const run = useCallback(async () => {
    try {
      const data = await loader.current()
      if (alive.current) setState({ status: 'ready', data })
    } catch (error) {
      if (alive.current) setState((s) => ({ status: 'error', data: s.data, error: toApiError(error) }))
    }
  }, [])

  useEffect(() => {
    alive.current = true
    setState((s) => ({ status: 'loading', data: s.data }))
    void run()
    let timer: ReturnType<typeof setInterval> | undefined
    if (refreshMs) {
      timer = setInterval(() => {
        if (document.visibilityState === 'visible') void run()
      }, refreshMs)
    }
    return () => {
      alive.current = false
      if (timer) clearInterval(timer)
    }
  }, [...deps, refreshMs, run])

  return { state, reload: run }
}

/** A clock that ticks so "x min ago" text and freshness labels stay honest while a page is open. */
export function useNow(intervalMs = 15_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}

export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine)
  useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [])
  return online
}
