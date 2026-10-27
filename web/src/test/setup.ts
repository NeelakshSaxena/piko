import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

// Dashboard pages are lazy chunks; their first import can take a while on a busy machine.
configure({ asyncUtilTimeout: 10_000 })

afterEach(() => {
  cleanup()
  window.sessionStorage.clear()
})
