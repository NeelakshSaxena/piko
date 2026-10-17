# Phase 6 (SOS and messaging) - independent security audit

Date: 2026-10-17. Reviewer: independent agent with no prior context (read-only review of source).
Verdict: **PHASE 6 GATE NOT PASSED.** No Critical or High finding. Server-side authorization and idempotency
are sound in the paths I tested. There are 3 Medium and several Low findings, one of which can lose an SOS
(F-01), plus stale or overstated evidence (section 5). This audit does not mark the phase complete.

## 1. Scope and method

Read in full: `prompts/INDEPENDENT_AUDIT.md`, `AGENTS`-referenced Phase 6 docs (ADR-022 + addendum, API_CONTRACTS
"As built in Phase 6" box, `docs/verification/phase-06-*.md`), `backend/app/services/{sos,messages,authz,principals}.py`,
`auth.py` (lockout diff), `api/routes.py` (SOS/messages), `api/schemas.py`, `core/{middleware,errors,ratelimit}.py`,
`api/deps.py`, `db/{models,session}.py`, migration `0004`, the three Phase 6 backend test files, web
`api/client.ts`, `SosContext.tsx`, `SosPage.tsx`, `MessagesPage.tsx`, `AlertsPage.tsx`, `lib/safety.ts`,
`vite.config.ts` (CSP), the test titles of `comms.test.tsx`, and Android `Comms.kt`, `SqliteCommStore.kt`, `net/ApiClient.kt`
(diff), `comms/*`, `AndroidManifest.xml`, the label strings of `CommsScreens.kt`.

Commands I ran (all read-only against isolated throwaway schemas):
- `.venv\Scripts\python -m ruff check backend` -> All checks passed.
- `.venv\Scripts\python -m mypy backend/app` -> Success, 29 files.
- `pytest backend/tests/test_phase6_hardening.py -q` -> **14 passed** in 111.7 s.
- A no-database check that psycopg 3.3.6 raises `DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes` when a
  string containing U+0000 is dumped (basis of F-02).

NOT done: I did not run the full backend suite, `test_api_sos.py`, `test_api_messages.py`, the web vitest suite, Gradle
unit tests or any emulator/device test, so I rely on the implementer's logs for those and could not confirm them. I did not
run a live exploit against a server, did not review `Layout.tsx`, `CommsScreens.kt` layout code, `MainActivity` or
`SharingService` beyond grep, did not review PostgreSQL server-side logging configuration, and did not open `.env`.
Findings marked "static" were derived by reading code, not by executing an attack.

## 2. Findings

### F-01 (Medium) A phone or browser whose clock runs more than 60 s ahead has its SOS permanently refused
- Evidence: `backend/app/services/sos.py:70-71` rejects `triggered_at > now + 60 s` with 400 (`telemetry_future_skew_seconds = 60`,
  `core/config.py:59`). `android/.../net/ApiClient.kt` `toResult()` maps every non-401/408/413/429/5xx status to `CommResult.Refused`;
  `core/Comms.kt:199-200` then calls `store.markFailed` and never retries. The same applies to messages
  (`messages.py:52-53`). The web composer stamps `sentAt = new Date().toISOString()` once (`MessagesPage.tsx:85`) and its
  Retry reuses that value, so a skewed browser can never send.
- Reproduction (static): set the phone clock 2 minutes ahead (manual time), press Send SOS. The server answers 400
  "triggered_at is in the future"; the item becomes FAILED and shows "Could not be sent (refused by server (HTTP 400
  VALIDATION_ERROR)). Contact your family another way."
- Impact: an emergency signal is dropped because of a clock error the child cannot see. The UI wording is honest, but the SOS is
  lost and no automatic recovery exists. Not covered by any test (the existing future-timestamp tests only assert the 400).
- Required fix: for SOS never reject on the claimed time. Store `triggered_at = min(claimed, received_at)` (keep the claim in a separate
  column or flag if wanted) and still return 201. On Android, treat 400 on an SOS as "re-stamp with the current clock and retry
  once" or at least keep it visibly retryable with a user "Try again" action. Add tests for both.

### F-02 (Medium) U+0000 in an SOS note, message or parent note causes HTTP 500 (not 400); Android then retries forever and the item blocks the queue
- Evidence: no control-character validation in `schemas.py:235-240,271-282`; the value reaches PostgreSQL (`sos.py:97`,
  `messages.py:75`, `sos.py:215` via commit). psycopg raises DataError (reproduced above), mapped by `core/errors.py:95-98` to
  500 INTERNAL_ERROR. `ApiClient.toResult` maps 5xx to `ServerError` -> `store.release()` -> back to QUEUED; `SqliteCommStore.next()`
  returns the same oldest SOS first every time (`ORDER BY kind ASC, seq ASC`), and `CommEngine.drain()` returns after the first retry,
  so one poisoned SOS stops every later SOS and message on that phone. `attempts` is counted but never used to give up or skip.
- Reproduction (static): POST `/api/v1/messages` with body `"a\u0000b"` -> 500. Paste a NUL into the Android note field.
- Impact: reliability/DoS of the child's own outbox by a character that is hard but not impossible to enter (paste, IME, a compromised
  client). On the parent side `PUT /sos/incidents/{id}` with a NUL note also returns 500 after the row lock is taken.
- Required fix: reject NUL (and other C0 controls except newline/tab) in the Request schemas with a 400 and test it; Android: after N
  server-error attempts for one item, move on to the next item instead of blocking the whole queue.

### F-03 (Medium) The dashboard SOS banner, nav badge and "Open" filter are computed from only the 100 newest incidents
- Evidence: `web/src/auth/SosContext.tsx:29-30` fetches `limit: 100` with no status filter and derives `openCount` from that page.
  The list is ordered by `received_at DESC` (`sos.py:157`). `SosPage.tsx:194` filters the same page client-side. Only the SOS page
  prints "the most recent N of M" (`SosPage.tsx:290`); the banner does not.
- Impact: if more than 100 newer incidents exist (a stuck or hostile device can create 10/min, see F-04), an older open SOS is
  neither counted in the banner nor listed. The banner would say "no open SOS" while one is open: a false reassurance in a safety
  view.
- Required fix: query `status=open` (or use `total_count`) for the banner/badge, and show a "more not loaded" warning wherever
  `has_more` is true.

### F-04 (Low) No per-device volume cap or de-duplication for SOS/messages; unbounded rows and audit rows
- Evidence: SOS create is limited to 10/min per device (`routes.py:371`), messages 30/min (`routes.py:455`); there is no daily cap,
  no coalescing of open SOS from one device, no retention job (ADR-022 admits no message retention; SOS rows "never deleted",
  `models.py` docstring). Every SOS writes a `sos_created` audit row (`sos.py:109`).
- Impact: a stolen/compromised child credential (or a buggy app) can create up to 14,400 open incidents/day, bury a real one
  (see F-03) and grow the database without limit. 500-char messages: about 21 MB/day/device.
- Required fix: cap open incidents per device (e.g. return the existing open one within N minutes or 409), per-device daily caps,
  and a documented retention job.

### F-05 (Low) Audit volume: incident detail reads have no per-user rate limit; list audit is throttled but check-then-insert is not atomic
- Evidence: `GET /sos/incidents/{id}` (`routes.py:407-410`) has only the 100/min per-IP global limit and always writes a
  `location_accessed` row (`sos.py:175,240-244`). Any authenticated parent/guardian can write ~144,000 audit rows/day by polling
  one id. The list throttle (`sos.py:225-239`) does a SELECT then INSERT without a lock, so concurrent lists can each write a row
  (harmless, bounded by 60/min).
- Required fix: add `rate_limit(... "sos-get", user, 60)` and consider the same throttle for repeat reads of the same id.

### F-06 (Low) Private conversation reads, message sends and acknowledgements are not audited; guardians can read the whole parent-child conversation
- Evidence: `messages.py` has no `audit.record` calls; `AUDIT_ACTIONS` (`models.py`) has no message action. A guardian is allowed to
  list a child's messages (`authz.visible_device` with `VIEW_ROLES`, used at `messages.py:124`; test `test_guardian_can_read_but_not_send_or_acknowledge`).
  The web composer card shown to parents does not say guardians can read the thread (only the guardian card does); Android says "parents
  and guardians" (`CommsScreens.kt:133`).
- Impact: access to children's private messages cannot be reconstructed afterwards; policy is still a pending operator decision
  (ADR-022 "decision needed").
- Required fix: operator decision on guardian read access; if kept, audit conversation reads (metadata only, throttled like the incident
  list) and tell parents on the web page that guardians can read.

### F-07 (Low) Messages from a parent can be hidden from the phone; second devices are invisible on the dashboard
- Evidence: Android `fetchParentMessages` requests `/messages?limit=50` and filters `sender == "parent"` client-side
  (`ApiClient.kt`); the endpoint returns both directions newest-first, so 50 or more newer child messages hide parent replies (and
  `announce` only sees those 50). Web `MessagesPage.tsx:57` and `AlertsPage.tsx:28` use only `devices[0]` per child, so messages from a second
  phone are never listed or counted in Alerts. `fetchSos` is similarly limited to 50.
- Required fix: add a server-side `sender` filter (and unseen-only filter), or raise/paginate; surface every device.

### F-08 (Low) Login lockout change: per-email advisory lock held during bcrypt; success resets the failure counter
- Evidence: `auth.py` login now takes `pg_advisory_xact_lock(hashtextextended(email_key))` before the user lookup and holds it through
  password verification (until commit/rollback); `_reject_if_locked` counts failures only since the last success of that user.
- Impact: (a) attempts for one email are serialised, so a flood against a victim's email (bounded by the 5/min per-IP limit) can add
  latency to that user's own login; (b) an attacker who guesses between a victim's successful logins gets a fresh budget of 9 attempts
  each time. The comment and test document (b) as intended; I note it as a trade-off, not a defect. The parallel test
  (`test_parallel_wrong_guesses_cannot_exceed_the_limit`) passed in my run and asserts exactly `limit` failures are recorded.
- Scope note: this is not SOS/messaging; it is a bundled backlog item (acceptable if declared, and it is declared in the test header).

### F-09 (Info) Existence oracle via 409 on id reuse
- Evidence: `sos.py:105-106`, `messages.py:93-99` answer 409 when a UUID is already used by another device/sender, while a fresh id
  creates a record. A device could learn that a given UUID exists elsewhere. UUIDv4 is unguessable and the probe creates a row for
  the prober, so risk is negligible. Retained for completeness; a replay with a different body silently returns the stored content
  with 200 (documented, tested).

### F-10 (Info) Clickjacking and header hardening are not in place for the one-click Acknowledge action
- Evidence: CSP is delivered as a build-time `<meta>` (`web/vite.config.ts:30`), where `frame-ancestors` is ignored; grep finds no
  `X-Frame-Options`/`frame-ancestors` header anywhere in `backend/app` or `web/index.html`. Acknowledge is one click (resolve has a confirm).
  Also the main.py comment on middleware order is stale (NoStore is now outermost) and unhandled-500 responses served by Starlette's
  outer error middleware do not carry `Cache-Control: no-store` (they contain no user data).
- Required fix: set `frame-ancestors 'none'` / `X-Frame-Options: DENY` at the serving layer (Phase 8) and record it as a known gap.

### F-11 (Info) Misleading comment about token storage
- Evidence: `web/src/api/client.ts:110-111` says the access token is "kept only in memory", but `sessionStorage` also holds
  `piko.access` and `piko.refresh` (`client.ts:66-96`, present in HEAD, not new). Phase 6 pages add no further storage; tests assert incident/message
  text is absent from both storages (`comms.test.tsx:220-225,308-313`). Fix the comment or the design; XSS would expose both tokens.

### F-12 (Info) Device-claimed times are unbounded in the past
- `triggered_at`/`sent_at` have a future cap but no lower bound (`sos.py:70`). A device may backdate an SOS (e.g. year 1970); the
  web shows both "Raised" and "Reached Piko" times and the delay chip, so this is visible, and open incidents still sort first.

## 3. Controls reviewed with no finding (what I actually tested or read)

1. Authentication and authorization (Q1), by reading code and the tests: every route uses `CurrentDevice`, `CurrentUser` or `AnyPrincipal`.
   Roles and membership are re-read from the database on each call (`authz.require_family_role`: pending -> 404, revoked -> 403, wrong
   role -> 403, inactive family excluded; `principals._authenticate_user` checks session and user status each request; device
   credential must be active, device not revoked, family active). SOS list: device sees only its own rows; users see only the family
   resolved by `view_family_id`, which requires an active VIEW role (child role -> 403). Detail: device must own it; user must have
   a VIEW role in the incident's family. Update: `ADMIN_ROLES` only after the row lock, using the incident's own family. Create:
   device only, body `device_id` must equal the authenticated device (`routes.py:372`), `family_id` comes from enrolment, never the request.
   Messages: device can only message and read its own conversation; a parent needs ADMIN role in the target device's family; list requires
   a visible device (child-role users only for their own device); ack allowed only for the opposite side, role-checked on the message's family.
   Guardian write refusal and cross-family 404 are enforced server-side and covered by tests (`test_api_sos.py:241-278`,
   `test_api_messages.py:114-160`). Not tested: revoked/pending membership and inactive family on these endpoints (gap, section 4).
2. Replay/concurrency (Q2): create and send use `INSERT ... ON CONFLICT (id) DO NOTHING RETURNING`, replay returns the stored row
   without rewriting it; `transition()` and `acknowledge()` lock the row with `FOR UPDATE`, check the allowed-transition table
   (open->acknowledged|resolved, acknowledged->resolved), and a repeat of the current state is a no-op, so resolved cannot reopen
   (also guarded by a CHECK constraint on values only). I found no way to move state backwards or overwrite stored content. A
   concurrent ack and resolve serialise correctly by inspection; there is no automated test for that interleaving.
3. SQL injection: all statements are SQLAlchemy Core/ORM with bound parameters; `status` is a `Literal`; `hide_parameters=True` is set
   (`session.py:21`) and the test confirms SQLAlchemy's `[parameters: ...]` dump is gone. PostgreSQL itself may still quote values in its
   own error text; the app logs only exception types (`errors.py:92,96,102`).
4. Input limits (Q4): UUID ids, `message` <=280, `body` 1..500 (whitespace stripped, so whitespace-only is rejected), `notes` <=500,
   lat/lon ranges and `allow_inf_nan=False`, accuracy 0..10000, unknown fields forbidden, body-size and gzip-bomb limits (`middleware.py`),
   `limit` caps (500 SOS / 200 messages), offset cap 100,000, per-principal rate limits plus the 100/min per-IP global limit. Numeric
   precision matches the column types.
5. Log/audit/error hygiene (Q5): request log line has method, path, status, request id only; validation errors report field names only;
   audit rows hold ids and actor only (tests assert no note, message or coordinates). Android notifications contain fixed text and
   `VISIBILITY_PRIVATE`; parent messages are held in memory on the phone, not persisted.
6. Web rendering (Q6): all user text (SOS note, parent note, message body, device names) is rendered as React text nodes; I found no
   `dangerouslySetInnerHTML`/`innerHTML`/`eval` in `web/src`. `credentials: 'omit'` and a bearer header mean cookie-based CSRF does not apply;
   Origin and Host allow-lists plus CORS are enforced server-side (`middleware.py`, `main.py`). `Cache-Control: no-store` is applied to every `/api/` response
   including 401/404 (test passed). Bidirectional-control characters are not stripped (possible text spoofing, cosmetic).
7. Truthfulness (Q7): server states are `open` (stored), `acknowledged`, `resolved`; "delivered" means stored. Web strings (`STATUS_TEXT`,
   `statusLine`, empty states, Alerts disclaimer) and Android `CommLabels` never say "sent"/"seen" for queued or merely stored items, and the
   web states that Piko does not contact emergency services and does not push. One wording to watch: the web hint "Acknowledging tells
   the child that a parent has seen the SOS" and the phone text "A parent confirmed they saw your SOS" are accurate only because
   acknowledgement is an explicit parent click; keep it explicit (do not add auto-acknowledge).
8. Android durability and honesty: item is written (`synchronous=FULL`, own DB file) before any network call, `INSERT ... CONFLICT_IGNORE`
   on a unique id, in-doubt items stay SUBMITTED and are re-sent with the same id, remote status only moves forward (`remoteRank`),
   job is `setPersisted(true)`, network ANY, exported=false with `BIND_JOB_SERVICE`; `RECEIVE_BOOT_COMPLETED` is declared with no
   receiver; `allowBackup=false`. The comms database is cleared on unlink and re-pair (`MainActivity.kt:128,163-164`). Not verified on a device.
9. Migration `0004`: tables, FKs, CHECKs and indexes match `models.py`; the downgrade drops safety records and says so. Not applied to the
   persistent `piko` schema (per the implementer's status file; I did not query the database).

## 4. Test quality (are negative cases real? any test that cannot fail?)

- Good negative coverage exists for: other family 404 with identical body to a nonexistent id, guardian 403, child-role 403, device 401 on PUT,
  anonymous 401, forged/unpaired device token, revoked device, id owned by another device/sender, bad enums, future/invalid timestamps, oversize
  fields, out-of-range coordinates, unknown fields, replay content not rewritten, and 6 concurrent identical creates producing one row.
  The lockout tests can fail (the "nine more failures" test would trip the old behaviour).
- Gaps (a defect here would not be caught): revoked or pending family member and inactive family on SOS/message routes; concurrent ack
  vs resolve and concurrent message ack; NUL/control characters (F-02); far-past timestamps; client clock skew (F-01); `GET /messages` by a
  device passing another device's id; detail-read audit volume; cache header on 429/500 responses; no XSS render test in `comms.test.tsx` (for
  example a note containing `<img onerror>`); the browser-storage assertions use `JSON.stringify({...window.localStorage})`, which relies on jsdom
  exposing keys as own properties (it probably works, but a stronger check is `Object.keys` / `getItem` loops).
- Weak assertions: `test_database_errors_do_not_carry_bound_values` only checks SQLAlchemy's text, and its own comment concedes PostgreSQL may
  still echo the value; `test_concurrent_duplicate_sends...` asserts `sorted(set(codes)) <= [200, 201]` (list comparison, obscure but not vacuous).
  Android: the live "attach fresh location" decision has no automated test (acknowledged in the Android report).

## 5. Unsupported or overstated claims in the evidence

1. **"262 passed" is stale for the current code.** `phase-06-backend-pytest.txt` was written 13:58; later edits include `auth.py` (14:25),
   `db/session.py` (14:25), `core/middleware.py` (14:26), `services/sos.py` (14:26) and the new `test_phase6_hardening.py` (14:31), none of which are in
   that run. Lint and mypy logs date from 13:38. I re-ran ruff, mypy and the hardening file (all pass), but no full-suite run of the final code exists.
2. **Reports say the web SOS Centre, Messages and Alerts are not built** (`phase-06-backend.md` line 3-4 and 33, `phase-06-android.md` line 3-4 and 37,
   `STATE.md` lines 5 and 19, ADR-020 addendum), yet `SosPage.tsx`, `MessagesPage.tsx`, `AlertsPage.tsx`, `SosContext.tsx` and `comms.test.tsx` exist.
   There is no web verification report and no recorded vitest/build/lint results for them, so the web part is **unverified by evidence**, and the
   documents are inconsistent with the tree.
3. ADR-022 line 325 ("`location_accessed` on every read of incidents") and the contract note ("Reads are audited") are no longer exactly true: list reads
   are now audited at most once a minute per user and an empty list is not audited; message reads are not audited at all (F-06).
4. The "Android 53 instrumented tests, 0 failed" row is stated to predate a label-only change; I could not rerun it. All Android results are emulator-only;
   the checklist `phase-06-physical-device-checklist.md` correctly says nothing was run on a phone. Do not cite Doze/reboot behaviour.
5. `phase-06-backend.md` lists 37 tests as the Phase 6 command; the hardening tests (14) and migration changes were added afterward and are not in that table.
6. The "Offline SOS is retained" row is true for the queue, but F-01 shows that a clock error turns a retained SOS into a permanent failure;
   the report does not mention this.
7. ADR-022 deviations (device-only SOS creation, guardian read-only incl. messages) are still "decision needed"; the code treats them as settled.

## 6. Dead code, duplication, scope

- `messages.py:66-71`: the parent path calls `admin_device` (which already runs `require_family_role(ADMIN_ROLES)`) and then runs the same
  role query again; harmless duplication.
- `sos.py` imports are all used (ruff clean). `_incident_out(..., for_family)` is the only place `parent_notes` is withheld from devices; it is tested.
- Unrelated or bundled changes in the diff: login lockout rewrite (F-08), `hide_parameters`, NoStore middleware, `core/security.py` comment change
  (ADR-009 -> ADR-008), `LaterPages.tsx` deletion, `Backoff.kt` extraction. They are declared as hardening/backlog and covered by tests, but they are outside
  "SOS and messaging" and each enlarges the review surface.

## 7. Required before the gate can be considered

1. Fix or consciously accept, with the operator, F-01, F-02 and F-03 (SOS loss on clock skew, 500 on NUL and queue blocking, banner computed from a truncated page).
2. Re-run the full backend suite, lint and mypy on the final tree and save logs; run and save web `vitest`, lint, typecheck and build logs; write the web verification report;
   correct the stale "web not built" statements in `STATE.md` and the two reports.
3. Operator decisions on ADR-022 (device-only SOS, guardian read of messages) and apply migration 0004 only after the stated backup.
4. Add the missing negative tests listed in section 4.
5. A physical-device run of the checklist before any claim about background delivery.

## 8. Verdict

No finding allows another family, a guardian, a child-role user, a revoked device or an anonymous caller to read, resolve, acknowledge or send, in the code paths I
read and the hardening tests I ran. That is a statement about this review, not a proof. The phase is **not ready to pass**: one realistic way to lose an SOS (clock skew),
one poison-input path (NUL), one false-reassurance path in the dashboard banner, and evidence that no longer matches the code. Human release policy decides the gate; I have not
marked it passed.
