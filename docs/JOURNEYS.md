# Piko Journeys

Journeys is a feature of the existing Android app: a person plans a trip leg by leg (flight, train, taxi, bike taxi,
metro, bus, walking, other), can follow it, and gets reminders and an honest picture of where they are. It is built on
the principle **the journey belongs to the phone; live data would only enrich it**. Everything below works with no
connection and with no third-party account.

Decisions: ADR-025 (builder, local store) and ADR-026 (backup, tracking, connections). Evidence:
`docs/verification/journeys-phases-0-6.md`. Source: `android/app/src/main/kotlin/app/piko/android/journeys/` and
`backend/app/services/journeys.py`.

## What it does

| Area | Behaviour |
|---|---|
| Builder | Create, edit, reorder (Earlier/Later buttons), save as draft or planned, delete. Times are typed as `yyyy-MM-dd HH:mm` with an IANA time zone per end of each leg. A draft needs only a title; "planned" needs both times on every leg, arrival after departure and no overlap between legs. |
| Backup (opt-in) | Off by default. When on, the whole journey is copied to the user's own Piko server (`PUT /api/v1/journeys/{id}`). Deletes are always sent for journeys the server holds. The phone stays the source of truth; nothing is ever pulled back. |
| Following | The user starts and stops it. Piko tracks which leg is current from confirmed arrivals only. One journey at a time. Pause, resume and stop are always visible. |
| Reminders | Alarms set on the phone before each leg (flight 2 h; train 30 min; bus and metro 15 min; taxi, bike taxi, walking and other 10 min), rebuilt after a reboot or update. Inexact on purpose; the text says when the leg is due. |
| Arrival | Confirmed by the user ("I've arrived"), or, if they chose it, noticed from this phone's location. Never from one reading (see below). The screen says which: "confirmed by you" or "noticed by location (not confirmed by you)". |
| Expected times | The user can say what they now expect (for example a delay). It sits beside the schedule and never replaces it. It is kept with the time it was entered, shown with its age, and distrusted after 3 hours. |
| Connections | For every leg not yet reached: `available = next departure - expected arrival`, `required = transfer + 15 min margin`, `slack = available - required`. Comfortable (>= 30 min), Tight (0-29), At risk (< 0), Unknown (time missing or update stale). The text states the numbers and that no live data is used. |
| Flight | The screen stays usable offline. After the expected arrival time passes it shows "Possible arrival, awaiting confirmation" (a clock guess, not a landing). A notification asks the user to confirm. With backup on, a small battery/connection reading is stored about every 20 minutes and sent when a connection returns. |

## Privacy and consent

- **Nothing leaves the phone unless the user turns backup on**, and the switch explains in words what is copied
  (places, times, flight and train numbers), where it goes (the server this phone is linked to) and that the family
  cannot see it. Turning it off stops uploads and discards events still waiting; copies already on the server stay until
  the journey is deleted (deleting a backed-up journey deletes its server copy and its events).
- **Who can read a backed-up journey:** only that device's credential through the API. The server **operator** and any logical
  backup of the database (`app.cli backup`) hold journeys in plain text, like the rest of the family data.
- **Family access: none.** Journeys are owned by one device. Only that device's credential can read or change them; a
  parent account, another device in the same family and another family all get "not found" or "wrong credential"
  (tests: `backend/tests/test_api_journeys.py`). Family milestone sharing (web dashboard) is a separate, later,
  separately reviewed decision.
- **Location**: used only if the user ticks "use this phone's location to notice arrival" when starting, grants precise
  location in the system dialog, and the leg has a destination position they picked. It runs as a visible foreground
  service with Pause and Stop. The last 12 readings are kept in memory only; **no trail is stored**. Destination
  coordinates are never uploaded.
- **Geocoding**: "Find this place on the map" sends the typed place name to the phone's own map service. It happens
  only on that tap and the user picks the match.
- **Booking references are not stored.** Adding them needs a protected-storage decision first.
- Events carry a type, a time and small flat values (a leg number, battery percent). Never a place name or a position.

### Retention

| Data | Where | Kept |
|---|---|---|
| Journey and legs | phone | until the user deletes it |
| Journey and legs | server (backup) | until the owner deletes it; a deleted journey leaves only an id tombstone (no title, legs or events) |
| Tracking session, arrivals | phone | with the journey |
| Events | phone | until delivered; undelivered events are dropped after 30 days; all dropped when backup is turned off |
| Events | server | 90 days (retention job), or when the journey is deleted |
| Last location readings | memory of the tracking service | the last 12, until the service stops |
| Notification de-duplication keys | phone | 14 days |

## Arrival detection rules (`ArrivalPolicy`)

At least two readings, each at most 5 minutes old and accurate to 150 m or better, all within 300 m of the chosen place,
spanning at least 2 minutes. A good reading elsewhere resets the wait. Stale, imprecise or missing readings give
"uncertain", never "arrived". Airport interiors and overlapping station areas make this unreliable, which is why the
user can always confirm by hand. Location detection pauses below 10% battery (back at 15%, or while charging).

## Providers: optional, off by default (ADR-027)

**Manual entry is the default and the source of truth.** Without any key every feature above works unchanged. A server
operator may switch on two optional data sources (`docs/SELF_HOSTING.md`): **Aviationstack** for flights and **RailRadar**
for Indian trains. No routing or taxi provider is integrated.

| | Aviationstack (flights) | RailRadar (trains) |
|---|---|---|
| Endpoint used | `GET api.aviationstack.com/v1/flights?access_key&flight_iata` | `GET api.railradar.in/v1/trains/{number}/live` |
| Auth | `access_key` query parameter (only documented method) | `Authorization: Bearer` |
| Free plan | 100 requests/month, **non-commercial**; paid from US$49.99/month | 100 requests/month, **personal/evaluation use**; paid from INR 499 (first month) |
| Used from the answer | `flight_status`, departure/arrival `delay`, gate, terminal | `status`, `delayMinutes` (if `isLive`), `lastUpdatedAt`, exception types |
| Not used | its timestamps (offsets could not be verified), historical date filter (paid) | route geometry, platforms, coaches, PNR, fares |
| Indian suitability | global; Indian airline/airport coverage and delay accuracy **not verified** | India-only; data said to derive from NTES; licence and accuracy **not verified**, no SLA on free |

How it behaves:

- The phone never holds a key. It asks its own Piko server, only when the user taps "Check live status" in the
  expected-time dialog, only for a flight/train leg with a valid number, and only from 6 hours before departure to
  3 hours after arrival. The dialog says what is sent (the flight number and date, or the train number).
- The answer is **shown, not stored**, labelled with its provider and "not your entry". The schedule is never touched. At
  most the user taps "Put these times in the boxes", reviews and saves them as their own expected time. Cancelled,
  not-live, older-than-3-hours readings and readings with no delay are shown but not offered. A delay the provider did
  not state is not shown as zero.
- If the provider is `manual`, has no key, is rate-limited, refuses the key, times out or answers in an unreadable shape,
  the screen says which in plain words and every time the user entered is unchanged and still works offline.
- Flight and train times are therefore either **typed by the user** or **typed by the user after reviewing a provider
  reading**. Piko does not auto-refresh, push delay alerts, or claim a landing.
- A confirmed landing is still not known: Aviationstack's `landed` status is shown as the provider's word only.
- Taxi and bike-taxi legs are manual entries; a booking reference grants no live vehicle tracking.

Limits specific to Indian rail: RailRadar is a third-party aggregator, not Indian Railways; delays can lag or be absent
for a run that has not started; the train-number lookup takes no date, so it describes the *current run*, which is why the
window exists. Do not rely on either source for a connection you cannot afford to miss.

## Limits worth knowing

- Reminders and the 20-minute reading are requests to Android, not guarantees. Doze, battery savers, a force-stop or an
  OEM battery manager can delay or skip them. Nothing here tries to evade those limits.
- The location service is never restarted by the system on its own. After a kill the screen says it is not running and
  offers a restart.
- "Network restored" is recorded only while the app process is alive; after a process death the sync job (which waits
  for a network) does the sending and no event is invented for the gap.
- Editing the schedule of a leg drops an update made against the old schedule.
- A time inside a daylight-saving gap is shifted by `java.time` rules without a warning.
- Date entry is typed text, not a picker; reordering uses buttons, not drag.

## Self-hosting

Migration `0007` adds `journeys`, `journey_legs` and `journey_events`. It is applied with the usual
`alembic upgrade head` after a backup (`docs/SELF_HOSTING.md`). Live data (above) needs no migration and no new service.
Without the migration the Android app still works fully offline; backup requests would be refused by the server.

## Verification still needed on hardware

Battery cost of the tracking service and the 20-minute job, behaviour under OEM battery managers, real arrival
detection while moving, and TalkBack/large-text passes have **not** been done. See the checklist added to
`docs/BATTERY_TEST_PROTOCOL.md`.
