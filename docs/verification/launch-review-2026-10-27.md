# Launch review (SEO, mobile, Core Web Vitals, accessibility, structured data, redirects, forms, conversion)

Method: code review of `web/`, plus a scripted headless-Edge run (CDP) at mobile (390x844, 4x CPU, slow-4G) and desktop (1366x768) against the live site and the local production build, using the checklist in FreeSiteAudit's "Claude Code website audit: developer checklist for launch" as the rubric. **The FreeSiteAudit tool itself was not run** (it is an interactive third-party service; nothing was submitted to it), so there is no side-by-side with its report. Re-run it on the deployed URL after this change ships. Script and raw results: `docs/verification/launch-audit/`.

## Must-fix launch blockers
Fixed in this working tree (not yet deployed):
1. **The landing page was `noindex` and had no description, canonical, social tags or structured data.** Search engines were told to skip it. Fixed: indexable landing, title, description, canonical, Open Graph, JSON-LD (SoftwareApplication with the two visible prices), `robots.txt` and `sitemap.xml`; app pages (`/login`, `/map`, ...) get an `X-Robots-Tag: noindex` header instead.
2. **`robots.txt` and `sitemap.xml` returned the app's HTML (200)** because the SPA rewrite caught them. Fixed with real files and a narrower rewrite.
3. **The page described features Piko does not have**: safe zones/geofence alerts, quick check-in buttons, a 3-second-hold SOS with siren, QR pairing, Docker Compose setup, multi-region/point-in-time backups, "encrypted at rest", high availability, one-click cancel, "standardized export formats". Misleading for a safety product. Fixed: copy now matches what exists; mock cards are labelled "Sample".
4. **No `<main>` landmark / skip link on the landing page**, mobile header overflowed (the menu button was pushed off-screen), several tap targets under 44 px, text as small as 10.4 px. Fixed (mobile tap-target failures 9 -> 4, smallest text 12 px, no horizontal overflow).

Still open and needs you:
5. **There is no way for a new family to sign up or pay.** Every "Get started" goes to Sign in; accounts are created only by the operator CLI; there is no billing, no contact form and no email address anywhere. The Hosted plan (₹300) cannot actually be bought. Decide: (a) add a contact/waitlist path (a `mailto:` is the smallest), (b) build signup + billing, or (c) reword the Hosted tier as "coming soon" and lead with self-hosting.
6. **Owner/legal/contact details are missing**: no privacy policy page, terms, or operator contact. The landing makes privacy promises ("we do not sell location data") with nothing backing them. Needed before collecting real families' data.
7. **Canonical domain**: everything points at `piko-web-jade.vercel.app`. If a custom domain is coming, change `index.html`, `public/robots.txt`, `public/sitemap.xml` first.

## Post-launch improvements
- Hero image `mascot.png` is a 205 KB PNG (the LCP element): mobile LCP measured 2.4-2.8 s on the throttled profile (limit for "good" is 2.5 s). Convert to WebP/AVIF at 1x/2x with `srcset`.
- Per-route `<title>` and meta (all routes share one title); a real 404 status for unknown paths (they return 200 and redirect client-side); a prerendered landing so crawlers and link previews do not depend on JavaScript.
- Add `width`/`height` to the small brand images; self-host a web font if one is added (none today).
- Tap targets: remaining 4 on mobile (FAQ `summary` rows, brand link). Desktop nav links are 21 px tall (fine for a pointer).
- A real `og:image` at 1200x630; verify structured data in Google's Rich Results test once deployed.
- Analytics/conversion events: none exist, so conversion cannot be measured. Add privacy-respecting counts for "Get started", "Deploy yourself", "Sign in".
- Dashboard pages: add visible focus-order checks with a screen reader (never done; jsdom axe passes, colour contrast is not checked in jsdom).

## Measured results (headless Edge)
| | Live site (before) | Local build (after) |
|---|---|---|
| robots meta | `noindex` | none |
| description / canonical / JSON-LD | none / none / 0 | yes / yes / 1 |
| `<main>` landmark | no | yes |
| Mobile horizontal overflow | no | no |
| Mobile tap targets < 44 px | 8 | 4 |
| Mobile LCP (throttled) | 3.97 s | 2.4-2.8 s |
| CLS (mobile and desktop) | 0 | 0 |
| Console errors, failed requests | 0 | 0 |
| Login / join: labelled inputs, one h1, `main` | yes | yes |
Axe (jsdom) accessibility tests pass for landing, login, join and the shell. Keyboard: first Tab reaches the brand link with a 3 px outline.
