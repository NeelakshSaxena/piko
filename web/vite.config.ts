import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, type Plugin } from 'vite'

function originOf(url: string): string {
  try {
    return new URL(url.replace('{s}', 'a')).origin
  } catch {
    return ''
  }
}

/** Production builds get a strict Content-Security-Policy; the dev server must stay CSP-free for HMR. */
function contentSecurityPolicy(env: Record<string, string>): Plugin {
  const api = originOf(env.VITE_API_BASE || 'http://127.0.0.1:8000')
  const tiles = env.VITE_TILE_URL === 'off' ? '' : originOf(env.VITE_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png')
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    `img-src 'self' data: blob:${tiles ? ' ' + tiles : ''}`,
    `connect-src 'self' ${api}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ')
  return {
    name: 'piko-csp',
    apply: 'build',
    transformIndexHtml: () => [
      { tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: policy }, injectTo: 'head-prepend' },
    ],
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_')
  return {
    plugins: [react(), contentSecurityPolicy(env)],
    build: { sourcemap: false, target: 'es2022' },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      restoreMocks: true,
      // Dashboard pages load lazily; the first import of each is slow on a busy machine.
      testTimeout: 20_000,
    },
  }
})
