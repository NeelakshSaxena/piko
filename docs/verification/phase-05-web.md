# Phase 5: parent web dashboard - completion report

**Date:** 2026-10-16. **Gate: NOT PASSED** (reasons at the end). Supersedes the web parts of
`phase-04-05-android-and-web.md`. Android work is paused by the operator's instruction (2026-10-16);
nothing in `android/` changed after that instruction except what is listed in that report.

Designs used: `screens/drishti_parent_web_command_dashboard`, `..._device_health_diagnostics`,
`..._live_family_map`, `..._sos_emergency_centre`, and the `tactile_clay_safety` design system.
The designs contain demonstration data ("Sample data", "Sandbox mode", people, places, heart rates,
satellites, an active SOS incident). **None of that is simulated in the product**: every number on
every page comes from the API, and an element the API cannot back is shown as Unknown/absent or is
omitted. That is the project rule ("No fake live data").

## Design coverage
| Design element | Built? | Notes |
|---|---|---|
| Sidebar: brand, family card, 9 nav items, user card | Yes | Brand is Piko with the supplied icon (designs say "Drishti"). SOS Centre, Messages, Alerts carry a **"Soon"** badge, not "LIVE" or a count. |
| Top bar: breadcrumb, sync chip, search, role chip | Yes | Sync chip = when the dashboard last read the server ("Synced 12 s ago"), turns amber if a refresh fails. Search finds people and pages (Ctrl+K). "Mesh Active" and the notification bell are omitted (no such thing exists). |
| Command Centre tiles | Partly | Phones reporting now, freshest location, lowest battery: real. Design's "Safety & Geofences" and "No Emergencies" tiles are replaced: there are no geofences, and "no emergencies" would be a false claim while SOS does not exist, so the tile says **"Not available yet"**. |
| Family roster & live status | Yes | Per child: status, location freshness + accuracy, battery + charging, network, last contact, links to map/activity/health. Avatars are initials (no photos exist). Age, school, "Request check-in", "Message" are not built (no data, Phase 6). |
| Safety timeline | Yes | Real recent events (location, battery, network) across children; link to the full log. |
| Live regional map preview | Yes | All phones, faded when not fresh. Geofence overlays, traffic, satellite view omitted. |
| Parent advisory note, emergency dispatch, school desk numbers, family PIN | No | No backing data or feature. |
| Live Family Map | Mostly | Map, member chips, filter, Fit all / Recenter, breadcrumb trail (last 4 h, gaps dashed), inspector with status, battery, network. Voice call, chime, trail stats, steps, speed, altitude, address omitted (not collected). |
| Device Health & Connectivity | Mostly | Phone picker, 4 status tiles, battery ring, location quality, delivery & sync (incl. readings delivered late from the offline queue), recent events table, CSV export, unlink. GNSS satellites, temperature, RSSI, mesh, "ping diagnostic" are omitted and the page says the phone app does not report them. |
| SOS Emergency Command Centre | **Page only** | A truthful "Not available in this version" page that tells people to call their local emergency number. The incident UI (triggered alert, audio, intercom, authorities, timeline) needs the SOS backend and Android SOS button: Phase 6. Building it now would show a fake emergency. |
| Messages, Alerts | Page only | Same: "Not available in this version". |
| Family Members | Yes | Adults (roles), children and phones, pairing code, invite code (replaces the old Manage page). |
| Settings | Minimal | Session facts, privacy facts, sign out. No password/retention/notification settings exist yet. |
| Tactile clay look, 26 px cards, pill buttons, wells, palette | Yes | Plus Jakarta Sans font is **not bundled** (needs a dependency approval); the system font is used. Muted text darkened to meet WCAG AA. |

## Backend change made for this phase
`GET /devices/{id}` now also returns `battery_is_charging`, `network_type`, `network_updated_at`
(already stored; `null` = never reported). Test added. Earlier in the phase: `GET /members/{id}/history`.

## Results (exact)
| Check | Result |
|---|---|
| `npm test` (vitest, jsdom) | **72 passed, 0 failed** (client 17, logic 11, pages 44; axe accessibility checks on login, join, overview, map, activity, health, family, and the three "not available" pages) |
| `tsc --noEmit`, `vite build` | exit 0; 473 kB JS (144 kB gzip), 27 kB CSS |
| `npm audit` | 0 vulnerabilities (110 packages) |
| Backend device-status tests | 3 passed (incl. the new fields); ruff and mypy clean |
| Production build with its strict CSP in a real browser | map tiles, API calls, tables and navigation work; **no CSP, CORS or load errors** |
| Layout at 390 px in a real browser | Overview, Map, Device Health: no horizontal overflow; sidebar becomes a swipeable bar |
| **Backend full suite on the final tree** | **NOT FINISHED when written**: `phase-05-backend-pytest.txt` (its last line `pytest exit N` is the result). An earlier run was stopped at 17% on purpose. |

## Not verified (why the gate is not passed)
- Backend full suite on the final code (above), and no independent audit of Phases 4-5.
- No screen-reader (NVDA/VoiceOver) pass; keyboard use only through automated tests and the skip link;
  colour contrast by calculation, not tooling.
- The map's default tiles are OpenStreetMap's public servers (fine for development, not for production).
- No physical Android device exists in the loop; live data in manual tests came from the emulator, which
  was closed during the final checks, so those screenshots show a stale phone (correctly labelled).
- Sidebar "Soon" areas, the Plus Jakarta Sans font, geofences, messaging and SOS are not built.
- Dashboard logout after a reload that interrupts an hourly token refresh is still possible (ADR-020).
