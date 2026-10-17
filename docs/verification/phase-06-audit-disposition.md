# Phase 6 independent audit: what was done about each finding (2026-10-17)

The audit itself (`phase-06-independent-audit.md`) was written by a separate reviewer with no prior context and was
**not edited**. Its findings were documented before any fix (project rule). This file records the remediation by the
implementer. The fixes have **not** been re-reviewed independently: that second look is still owed before anyone
treats a finding as closed beyond "fixed and tested".

| ID | Severity | Disposition | Evidence |
|---|---|---|---|
| F-01 clock skew loses an SOS | Medium | **Fixed**: a future claim is capped at receipt time (SOS and messages) | `test_phase6_audit_fixes.py` (61 s, 2 h, 400 days; message; garbled time still 400; 1970 stored as claimed); the two old "future time is 400" assertions were removed from `test_api_sos.py`/`test_api_messages.py` because they asserted the defect, replaced by these |
| F-02 NUL in text -> HTTP 500, Android retries forever and blocks the queue | Medium | **Fixed**: 400 for control characters (server), sanitised on the phone, and one failing item (3 failures) goes behind the others but is never dropped | server: 4 bad strings x SOS note / message / parent note, nothing changed in the database, value not echoed, newlines/tabs/Unicode accepted; Android: contract test on JVM fake and real SQLite, `CommPoisonTest`, model/sanitiser tests |
| F-03 banner/badge from the newest 100 only | Medium | **Fixed**: second read for all open incidents, server count used when more than a page, truncation warning | 3 web tests incl. an open SOS older than 100 newer ones |
| F-04 no volume cap / retention | Low | **Open, accepted pending decision** (ADR-022 addendum 2) | limits 10 SOS/min, 30 msgs/min per device |
| F-05 detail read not rate limited; list audit not atomic | Low | **Fixed** (60/min/user); the list audit race stays (bounded, harmless) | `test_incident_detail_reads_are_rate_limited` |
| F-06 conversation reads not audited; guardians read everything | Low | **Open (decision)**; the web page now tells parents that guardians can read | web test; no audit action exists for messages |
| F-07 parent replies can be hidden; second device invisible | Low | **Fixed** for the phone (server `sender` filter; and own-message status is now pulled). Web lists only each child's first device (pairing makes one child identity per device) | `test_messages_can_be_filtered_by_sender...`, Android engine + client tests |
| F-08 lockout lock held through bcrypt; reset after success | Low | **Accepted trade-off**, declared | `test_phase6_hardening.py` |
| F-09 409 existence oracle | Info | Accepted (UUIDv4, prober creates a row) | |
| F-10 clickjacking header | Info | **Open, Phase 8** (static host); mitigation explained in ADR-022 addendum 2 | |
| F-11 token-storage comment | Info | **Fixed** (comment corrected) | `web/src/api/client.ts` |
| F-12 no lower bound on claimed time | Info | Accepted; both times are shown | test |

Missing negative tests listed by the audit, now added in `test_phase6_audit_fixes.py`: revoked member, pending
member, archived family, another device's conversation, child-role user, concurrent acknowledge vs resolve (8
threads, never a 500, resolved wins and stays), concurrent message acks, far-past claims, control characters.
Web: markup in notes/messages renders inert; storage is checked by iterating keys and values (not by JSON-ing the
storage object). Not added: a 429/500 `Cache-Control` test (500s come from Starlette's outer handler).

Evidence problems the audit raised and how they were handled: the stale "262 passed" log is replaced by a full run
on the final tree (`phase-06-final-backend-pytest.txt`); the reports that said the web pages were not built were
corrected (`STATE.md`, `phase-06-backend.md`, `phase-06-android.md`, new `phase-06-web.md`); ADR-022 and the contract
note now describe the throttled list audit; the web results are recorded (`phase-06-web-tests.txt`); the Android
instrumented suite was re-run on the final code including the label wording.
