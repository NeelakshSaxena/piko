# Free-tier deployment architecture and runbook

Status: **designed and prepared; NOT deployed.** No GitHub, Vercel or Firebase access was authenticated in this session, so nothing here has run remotely. Every limit below must be re-checked on the provider's pricing page at sign-up; they change.

## Architecture

| Part | Host | Why |
|---|---|---|
| Web dashboard (static Vite SPA + `sw.js`) | Vercel Hobby (`web/vercel.json`) | Static hosting fits Hobby well. Hobby is **non-commercial, personal use only**. |
| API (FastAPI) | Vercel Python Function via `backend/index.py` (`backend/vercel.json`, `backend/requirements.txt`) | Piko has no persistent worker: the outbox is durable and drained per request, by an external cron call, or by pg_cron. Cold starts and the function duration limit apply. |
| Database | existing Supabase Postgres (free) | Free projects pause after inactivity; use the pooled connection string as a Vercel secret. |
| CI | GitHub Actions (`.github/workflows/ci.yml`) | Free minutes for private repos are limited; public repos are unmetered. Repo visibility is the owner's decision. |
| Outbox/retention scheduler | GitHub Actions cron (`scheduler.yml`, best-effort, minimum 5 min, can be delayed) and/or Supabase `pg_cron` + `pg_net` calling `/api/v1/internal/outbox/run` | Vercel Hobby cron is **once per day only** and cannot be the scheduler. |
| Push to phone | Firebase Cloud Messaging (no cost) | Needs a Firebase project (Spark, no billing). |
| Push to parent browsers | W3C Web Push with own VAPID keys | No third-party account. |

Rejected: Vercel Hobby cron as the only drain (daily); a persistent worker on a free host (free web services sleep/idle and may require a card; if you prefer one, any container host running `python -m app` plus `python -m app.cli outbox --loop` works unchanged).

Cost-risk summary: no paid plan is required for the design. Risks: Hobby fair-use limits, Supabase auto-pause (first request after a pause is slow/fails), GitHub cron delay, and Hobby's non-commercial restriction. Nothing here enables billing.

## Environment variable inventory (names only)

Backend (`PIKO_` prefix): `ENV`, `DATABASE_URL` (secret), `DB_SCHEMA`, `JWT_PRIVATE_KEY_B64` (secret), `HMAC_KEY_B64` (secret), `FCM_PROJECT_ID`, `FCM_SERVICE_ACCOUNT_B64` (secret), `VAPID_PRIVATE_KEY_B64` (secret), `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT`, `OUTBOX_RUN_TOKEN_B64` (secret), optional live data: `FLIGHT_DATA_PROVIDER`, `AVIATIONSTACK_API_KEY` (secret), `RAIL_DATA_PROVIDER`, `RAILRADAR_API_KEY` (secret) (leave unset for manual-only; see `docs/SELF_HOSTING.md`), `ALLOWED_ORIGINS` (JSON list; must contain the deployed web origin) and `PUBLIC_BASE_URL`, plus tunables in `app/core/config.py` (retries, TTLs, caps, retention days).
Web build: `VITE_API_BASE`, `VITE_TILE_URL`.
GitHub: variable `PIKO_API_URL`; secret `PIKO_OUTBOX_RUN_TOKEN`.
Android build (gitignored `local.properties`): `piko.firebase.projectId|appId|apiKey|senderId`.

## Runbook (needs the owner; none of it was executed)

1. Review and approve this repository state; commit/push is the owner's action.
2. Back up the database and verify the restore (see the gate report); only then apply migrations (0004 then 0005) to the target schema. Never to an unverified or production schema without approval.
3. Create the Firebase project (docs/PUSH_NOTIFICATIONS.md); generate VAPID keys with `python -m app.cli generate-push-secrets`.
4. Vercel: import the repo twice (root `web` and root `backend`), add the secrets above in the dashboard (not in files), set `ALLOWED_ORIGINS` and `PUBLIC_BASE_URL` to the web preview/production URL, deploy a **preview** first.
5. Smoke test with synthetic data only: `/api/v1/health/ready`, register a synthetic family, pair, SOS, check outbox health at `/api/v1/internal/outbox/health`.
6. Set GitHub variable/secret for the scheduler.
7. Authenticate the GitHub and Vercel MCP servers in an interactive session (`/mcp`); GitHub needs `PIKO_GITHUB_MCP_PAT` in the environment with minimum scopes.

## Verification status

CI workflow: written, not run (no GitHub). Vercel preview: not created. Deployed-app smoke test: **blocked**.
