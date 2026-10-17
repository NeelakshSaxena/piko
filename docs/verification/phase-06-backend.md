# Phase 6 — SOS and messaging: backend part

> **Superseded in parts (2026-10-17, later the same day):** the web pages now exist (`phase-06-web.md`), an
> independent audit ran (`phase-06-independent-audit.md`, remediation in `phase-06-audit-disposition.md`), and the
> backend changed after the runs listed below (audit fixes, hardening). The authoritative, final results are in
> `phase-06-gate-report.md`. The tables below are kept as the historical first-pass record: the "262 passed"
> full run and the "37 passed" focused run predate those changes.

## What exists
- `backend/migrations/versions/0004_sos_and_messages.py`: `sos_incidents`, `messages`, audit action `sos_acknowledged`.
- `backend/app/services/sos.py`, `messages.py`; routes in `backend/app/api/routes.py`; DTOs in `schemas.py`; `authz.view_family_id`.
- Design and open decisions: `docs/DECISIONS.md` ADR-022; contract note in `docs/API_CONTRACTS.md`.

## Tests (real PostgreSQL, isolated schema)
| Command | Result |
|---|---|
| `.venv\Scripts\python -m pytest backend/tests/test_api_sos.py backend/tests/test_api_messages.py backend/tests/test_migrations.py -q -x` | 37 passed, 1 warning (httpx/starlette deprecation), 334.98 s |
| `ruff check backend` | `phase-06-backend-lint.txt`: exit 0 |
| `mypy backend/app` | `phase-06-backend-mypy.txt`: exit 0 (29 files) |
| Full backend suite | `phase-06-backend-pytest.txt`: **262 passed**, 1 warning, `pytest exit 0` (19m48s) |

## Phase 6 "Verification" list vs evidence
| Requirement | Status |
|---|---|
| Offline SOS is retained | Server accepts an SOS triggered hours earlier (test). Android: see `phase-06-android.md` (tests + live emulator run). |
| Reconnect sends exactly one incident | Server idempotency incl. 6 concurrent sends -> one row (test). Android: see `phase-06-android.md`. |
| Queued is not shown as delivered | Android labels (unit-tested) and live run: see `phase-06-android.md`. |
| Unauthorized users cannot read or resolve | Tested: other family 404 (same body as nonexistent), guardian 403 on writes, child role 403, device 401 on PUT, anonymous 401. |
| Acknowledgement does not auto-resolve | Tested. |
| Notification permission denied handled honestly | Android, verified on the emulator: see `phase-06-android.md`. |
| Duplicate/replayed requests do not duplicate events | Tested for incidents (one `sos_created` audit row too) and messages. |
| Audit without message bodies | Tested: no message text, notes or coordinates in audit rows. |

## Not done / limitations
(Web pages and Android now exist, see the notes at the top); any push to parents (none exists); message retention job; operator approval of
ADR-022 deviations (device-only creation, guardian read-only); independent audit (required for
this security-critical phase); migration 0004 not applied to the persistent `piko` schema; nothing
run on a physical device.
