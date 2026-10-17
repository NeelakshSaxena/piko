# Phase 6 — parent web dashboard (SOS Centre, Messages, Alerts)

Date: 2026-10-17. Supersedes the earlier statements in `phase-06-backend.md`, `phase-06-android.md` and
`STATE.md` that said these pages were not built.

## What was built (no new dependency; same Vite + React + react-router + Leaflet stack)
| File | Role |
|---|---|
| `web/src/pages/SosPage.tsx` | SOS Centre: list/filter, status chips, position provenance and currency, map for the selected incident, Acknowledge, Resolve with confirmation, guardian view-only, conflict/refusal/network states |
| `web/src/pages/MessagesPage.tsx` | Conversation per child phone, composer (parents/admins), in-memory outbox with stable message ids, Retry, "Mark as seen", guardian read-only |
| `web/src/pages/AlertsPage.tsx` | One list from incidents, unseen child messages, and notices *derived* in the browser (labelled) |
| `web/src/auth/SosContext.tsx` | One poller (30 s while visible) shared by the app-wide banner, the nav badge, SOS and Alerts |
| `web/src/lib/safety.ts`, `newId.ts` | Pure wording/ordering/currency rules; v4 id with a fallback for plain-http hosts |
| `web/src/api/client.ts`, `types.ts` | `sosIncidents`, `updateSos`, `messages`, `sendMessage`, `acknowledgeMessage`; a reply of the wrong shape is an error, never an empty list |
| `web/src/components/Layout.tsx`, `OverviewPage.tsx`, `styles.css` | SOS banner (also when the check itself fails), nav count, the Overview SOS tile shows real data, claymorphism tokens reused |
`LaterPages.tsx` (the "Not available in this version" placeholders) was removed; its three tests
(`areas that do not exist yet`) and the Soon-badge assertions were **replaced** by the new page tests, and the
Overview "SOS: Not available yet" test now asserts the real tile ("None open ... not proof anyone is safe").

## Results (commands run on the final tree; logs: `phase-06-web-tests.txt`)
| Command | Result |
|---|---|
| `tsc --noEmit` | exit 0 |
| `vitest run` | **116 passed, 0 failed** (4 files). Before this work: 72; 4 placeholder tests were removed (68), then added: 37 page tests, 3 client tests, 7 audit-remediation tests (banner truncation x3, XSS/storage x3, guardian note), 1 resolve-closes-panel regression |
| `vite build` (production, CSP injected, `VITE_TILE_URL=off`) | exit 0, 53 modules |
No eslint is configured in this project (not added: no dependency approved).

## What the web tests prove (all against a fake server; no mocking of the page logic)
Open is not worded as acknowledged; acknowledge does not resolve and keeps the resolve action; resolve needs a
confirmation and Cancel changes nothing; a resolved incident has no actions and no live confirmation panel; a 409 is
explained and the list refreshed; guardians get no buttons; a server 403 is shown as a refusal; last-known position
is labelled with its own time; stale is "Not current"; a position older than 24 h is a "Recorded position"; delayed
arrival (offline) is shown; no position is stated plainly; banner/nav count on every page; a failed check is not "none";
the banner counts an open SOS older than the newest 100 (server count used when > 100 open) and a truncated list says
so; messages: wording never claims "seen" for a stored message; send posts once with a stable id; a failed send stays
visible and Retry reuses the id (server stores once); mark-as-seen only on the button; guardians cannot send or mark;
note/message text never in localStorage/sessionStorage (keys and values); `<img onerror>` / `<script>` in a note,
parent note or message render as inert text; Alerts merges sources, sorts, links, labels derived notices, names a failed
source, and has an honest empty state; axe-core has no violations on SOS, Messages, Alerts and the shell
(colour contrast is not checked in jsdom).

## Live check (real browser, real backend, real emulator; throwaway schema `piko_test_e2e_1fc14f`)
Chrome against the production build served by `vite preview` (port 4173) and the API on `127.0.0.1:8000`:
- SOS Centre showed the banner ("N SOS alerts are open and not yet acknowledged"), a nav count, the incident with
  "Last known position, not sent with the SOS", "Not current · last seen 37 min ago" and the explanation text.
- Acknowledge from the page -> the phone showed "A parent confirmed they saw your SOS"; the incident stayed
  "Acknowledged · not resolved". Resolve showed the confirmation text ("cannot be reopened"), then Resolved.
  **Bug found and fixed:** after resolving, the confirmation panel stayed on screen with live buttons; fixed and
  covered by a regression test, then rebuilt.
- Messages: dashboard message showed "Sending…" then "Delivered to the Piko server. The phone has not confirmed
  seeing it."; the phone fetched it ("Got it") and the page then said "The phone confirmed it was seen"; the phone's
  own message showed "No parent has marked it as seen" until "Mark as seen" was pressed. **Gap found and fixed:** the
  phone never pulled the status of its own messages, so "Seen by a parent" could not appear; fixed (Android + test).
- Alerts listed open SOS first ("Needs action") and a derived "has gone quiet" notice labelled "Phone status (derived)".
- Browser console: no messages were captured on the production build (tracking began after the first load, so a CSP
  violation during the first load of a page would not have been seen); the API calls (including CORS preflights) returned 200.
Screenshots: the Chrome captures were not saved into the repository; Android captures are in
`artifacts/android/phase6/` and `artifacts/android/phase6-final/`.

## Not done / limitations
- No screen-reader or keyboard-only pass in a real browser; no colour-contrast measurement of the new components; no
  responsive screenshots at phone/tablet widths (CSS has a 600 px rule; unverified visually).
- Only the first device of a child is listed in Messages/Alerts (pairing creates one child identity per device, so this
  holds today); a family with several phones shows several "children" with the same device name (seed artefact of the
  test schema: the Messages dropdown showed three identical names).
- Parents are not notified: no push; the page is only current while open and visible (30 s).
- Guardians' reads of the conversation are not audited (accepted, ADR-022 addendum 2).
- Clickjacking headers belong to the static host (Phase 8).
