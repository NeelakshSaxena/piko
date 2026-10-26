// Drives headless Edge over CDP: loads a URL at a mobile and a desktop viewport and reports launch-audit facts.
import { spawn } from 'node:child_process'
import { writeFileSync, mkdirSync } from 'node:fs'

const [url, outDir, tag] = process.argv.slice(2)
mkdirSync(outDir, { recursive: true })
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const port = 9333 + Math.floor(Math.random() * 500)
const edge = spawn(EDGE, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=G:/Projects/piko/.tmp/edge-${port}`, '--no-first-run', '--disable-gpu', 'about:blank'], { stdio: 'ignore' })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let targets
for (let i = 0; i < 40; i++) {
  try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (targets.length) break } catch {}
  await sleep(250)
}
const page = targets.find((t) => t.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((r) => (ws.onopen = r))
let id = 0
const pending = new Map()
const events = []
ws.onmessage = (m) => {
  const d = JSON.parse(m.data)
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id) } else events.push(d)
}
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })
const evalJs = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.result?.value

const PROBE = `(() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' }
  const q = (s) => [...document.querySelectorAll(s)]
  const name = (el) => (el.getAttribute('aria-label') || el.textContent || el.getAttribute('title') || '').trim()
  const small = q('a,button,input,select,textarea,summary').filter(vis).filter((el) => { const r = el.getBoundingClientRect(); return r.height < 44 || r.width < 44 }).map((el) => el.tagName.toLowerCase() + ':' + name(el).slice(0, 30) + ' ' + Math.round(el.getBoundingClientRect().width) + 'x' + Math.round(el.getBoundingClientRect().height))
  const heads = q('h1,h2,h3,h4').map((h) => +h.tagName[1])
  let skips = 0; for (let i = 1; i < heads.length; i++) if (heads[i] - heads[i - 1] > 1) skips++
  const imgs = q('img')
  return {
    title: document.title,
    description: document.querySelector('meta[name=description]')?.content || null,
    canonical: document.querySelector('link[rel=canonical]')?.href || null,
    robotsMeta: document.querySelector('meta[name=robots]')?.content || null,
    og: !!document.querySelector('meta[property="og:title"]'),
    jsonld: q('script[type="application/ld+json"]').length,
    lang: document.documentElement.lang,
    h1: q('h1').length, headingSkips: skips,
    imgsNoAlt: imgs.filter((i) => !i.hasAttribute('alt')).length,
    imgsNoSize: imgs.filter((i) => !(i.getAttribute('width') && i.getAttribute('height'))).map((i) => i.getAttribute('src')),
    imgsLazy: imgs.filter((i) => i.loading === 'lazy').length, imgCount: imgs.length,
    unnamedLinks: q('a').filter((a) => !name(a) && !a.querySelector('img[alt]')).length,
    unnamedButtons: q('button').filter((b) => !name(b)).length,
    unlabelledInputs: q('input,select,textarea').filter((i) => i.type !== 'hidden' && !i.labels?.length && !i.getAttribute('aria-label') && !i.getAttribute('aria-labelledby')).length,
    horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    smallTargets: small.length, smallTargetSamples: small.slice(0, 8),
    smallestFont: Math.min(...q('p,li,a,span,button').filter(vis).map((e) => parseFloat(getComputedStyle(e).fontSize))),
    hasMain: !!document.querySelector('main,[role=main]'), hasNav: !!document.querySelector('nav'),
    anchors: q('a[href^="#"]').map((a) => a.getAttribute('href')).filter((h) => h.length > 1 && !document.querySelector(h)),
    bodyTextLength: document.body.innerText.length,
    mobileToggleVisible: (() => { const t = document.getElementById('piko-mobile-toggle'); return t ? vis(t) : null })(),
  }
})()`

const result = {}
for (const [label, w, h, mobile] of [['mobile', 390, 844, true], ['desktop', 1366, 768, false]]) {
  events.length = 0
  await send('Page.enable'); await send('Runtime.enable'); await send('Log.enable'); await send('Network.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: mobile ? 3 : 1, mobile })
  if (mobile) await send('Emulation.setTouchEmulationEnabled', { enabled: true })
  await send('Emulation.setCPUThrottlingRate', { rate: mobile ? 4 : 1 })
  await send('Network.emulateNetworkConditions', mobile ? { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 } : { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `window.__cls=0;window.__lcp=0;new PerformanceObserver(l=>{for(const e of l.getEntries())if(!e.hadRecentInput)window.__cls+=e.value}).observe({type:'layout-shift',buffered:true});new PerformanceObserver(l=>{const e=l.getEntries();window.__lcp=e[e.length-1].startTime}).observe({type:'largest-contentful-paint',buffered:true});` })
  await send('Page.navigate', { url })
  await sleep(mobile ? 9000 : 4000)
  const facts = await evalJs(PROBE)
  const perf = await evalJs(`(() => { const n = performance.getEntriesByType('navigation')[0]; const r = performance.getEntriesByType('resource'); return { lcpMs: Math.round(window.__lcp), cls: +window.__cls.toFixed(4), domContentLoadedMs: Math.round(n.domContentLoadedEventEnd), loadMs: Math.round(n.loadEventEnd), transferKB: Math.round(r.reduce((a, e) => a + (e.transferSize || 0), 0) / 1024), requests: r.length, biggest: r.sort((a, b) => b.transferSize - a.transferSize).slice(0, 3).map((e) => e.name.split('/').slice(-2).join('/') + ' ' + Math.round(e.transferSize / 1024) + 'KB') } })()`)
  const consoleErrors = events.filter((e) => (e.method === 'Runtime.exceptionThrown') || (e.method === 'Log.entryAdded' && e.params.entry.level === 'error')).map((e) => (e.params.entry?.text || e.params.exceptionDetails?.text || '').slice(0, 160))
  const failed = events.filter((e) => e.method === 'Network.loadingFailed').length
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  writeFileSync(`${outDir}/${tag}-${label}-top.png`, Buffer.from(shot.result.data, 'base64'))
  const full = await send('Page.captureScreenshot', { format: 'jpeg', quality: 55, captureBeyondViewport: true })
  writeFileSync(`${outDir}/${tag}-${label}-full.jpg`, Buffer.from(full.result.data, 'base64'))
  // Keyboard: does Tab reach a visible, focus-styled element?
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 })
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 })
  const focus = await evalJs(`(() => { const a = document.activeElement; if (!a || a === document.body) return null; const s = getComputedStyle(a); return { tag: a.tagName, text: (a.textContent||'').trim().slice(0,30), outline: s.outlineStyle + ' ' + s.outlineWidth, shadow: s.boxShadow.slice(0,40) } })()`)
  result[label] = { facts, perf, consoleErrors, failedRequests: failed, firstTabFocus: focus }
  await send('Emulation.clearDeviceMetricsOverride')
}
writeFileSync(`${outDir}/${tag}.json`, JSON.stringify(result, null, 2))
console.log(JSON.stringify(result, null, 2))
ws.close(); edge.kill()
process.exit(0)
