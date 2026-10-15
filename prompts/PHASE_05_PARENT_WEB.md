# Phase 5 — Parent Web Dashboard

## Goal
Implement the existing `screens/` designs as a responsive parent safety dashboard, preserving the approved claymorphic Piko design system.

## Scope
- Authentication pages.
- Family overview.
- Map and member selection.
- Freshness/accuracy indicators.
- Device status/telemetry.
- Activity and history.
- Loading, empty, offline, stale, denied, and error states.
- Typed API client and minimal reusable components.

## Rules
- Inspect `screens/` first and map assets to screens.
- Do not redesign without documenting why the existing design cannot meet requirements.
- No fake live data in production UI.
- Demo fixtures must be clearly labelled and isolated from production builds.
- UI visibility is not authorization; server remains authority.
- Keep bundle and dependencies minimal.

## Verification
- Responsive layout at agreed viewport sizes.
- Keyboard and screen-reader checks.
- Stale location never labelled live.
- Unavailable data shown as unknown, not zero.
- API errors and expired session handled.
- Cross-family authorization tested at API, not only in UI.
- Web dependencies and caches remain project-local.
