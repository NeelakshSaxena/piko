# Piko Journeys — Android implementation plan

Product specification · Architecture · Data model · APIs · Permissions · Delivery roadmap

We're going to build Piko Journeys as a native Android capability inside the existing Piko app, not as a separate travel application. The goal is to take a user from their starting point to their final destination, across multiple transport modes, while keeping the itinerary, connection decisions and tracking state coherent—even when the phone loses connectivity.

The central engineering principle: the journey belongs to the device; live travel data enriches it. If the network disappears during a flight, Piko must still know the itinerary, the current leg, what should happen next and what information needs to synchronize later.

I would divide the implementation into five major systems:

1. Journey Builder — create and arrange transport legs.
2. Transport Intelligence — flight, rail, taxi, metro and routing integrations.
3. Journey Engine — determine the current state and next action.
4. On-device Tracker — location, geofences, offline operation and notifications.
5. Journey Sync — persist, synchronize and recover the journey across app restarts and connectivity changes.

The first release should establish all five foundations, then add progressively more sophisticated automation. We should not make the whole product depend on a flight API or a taxi provider being available.

## 1. Fit with the existing Piko repository

I inspected the public [Piko repository](https://github.com/NeelakshSaxena/piko?utm_source=chatgpt.com), including its Android application, backend routes, database models, project instructions and architecture.

The good news: the core infrastructure needed for Journeys already exists. We should extend it instead of rebuilding it.

Android: Kotlin + Jetpack Compose

The app already has a hand-wired `AppGraph`, a `SharingService`, a SQLite event store, a durable recorder and an offline synchronization engine. These are natural integration points for the trip engine.

Existing paths: `android/app/src/main/kotlin/app/piko/android/`

Backend: FastAPI + SQLAlchemy

The existing API uses `/api/v1`, explicit request/response schemas, authenticated principals, service-layer authorization and database migrations. Journeys should follow these same conventions.

Existing paths: `backend/app/api/`, `backend/app/services/`, `backend/migrations/versions/`

Existing security and offline-first rules

Piko already emphasizes durable store-and-forward behavior, idempotent event ingestion, explicit location permissions, no hidden tracking and self-hostability. Journeys should preserve all of these.

One important distinction: the repository's existing device telemetry and location-sharing capabilities are not yet a complete trip-management system. Flight integrations, multi-leg itineraries, travel-state transitions, trip-specific notifications and offline flight recovery still need to be designed and implemented.

I recommend keeping the first implementation in the current Android module and backend modular monolith. No microservices, no separate travel database server, and no mandatory proprietary cloud.

## 2. Target architecture

Piko Android · Journey UI

Builder · Itinerary · Live timeline · Settings

Journey domain

TripRepository · JourneyEngine · ConnectionPlanner · State reducer

Device runtime

Room or SQLite persistence, location, geofences, foreground service, offline event queue

Piko backend

Trip API, persistence, flight/rail refresh, authorization, synchronization

Provider adapters

Flight status · Rail status · Maps and ETA · Supported taxi APIs

### Proposed Android package structure

Add the following packages under `android/app/src/main/kotlin/app/piko/android/`:

```
journeys/
├── domain/
│   ├── Journey.kt
│   ├── JourneyLeg.kt
│   ├── JourneyState.kt
│   ├── JourneyEngine.kt
│   └── ConnectionPlanner.kt
├── data/
│   ├── JourneyRepository.kt
│   ├── JourneyDao.kt
│   ├── JourneyLocalStore.kt
│   └── JourneySync.kt
├── tracking/
│   ├── JourneyTracker.kt
│   ├── GeofenceManager.kt
│   ├── FlightOfflineRecorder.kt
│   └── JourneyNotifications.kt
├── providers/
│   ├── FlightProvider.kt
│   ├── RailProvider.kt
│   ├── RoutingProvider.kt
│   └── TaxiProvider.kt
└── ui/
    ├── JourneyListScreen.kt
    ├── JourneyBuilderScreen.kt
    ├── JourneyDetailScreen.kt
    └── JourneyViewModel.kt
```

This is a proposed structure, not a claim that these files already exist.

Integrate dependencies through `AppGraph` rather than introducing a second dependency-injection framework. Reuse Piko's existing theme, authentication, credential vault, network client and synchronization conventions.

Persistence decision: use the existing SQLite infrastructure if it can support transactional journey records cleanly. If the implementation benefits from Room's structured relations and observable queries, migrate or extend the local store deliberately rather than maintaining two independent databases for the same journey data.

## 3. Data model

Use stable UUIDs, explicit enums, UTC timestamps internally, and IANA time-zone identifiers for displaying departure and arrival times. Flight and rail times must preserve the provider's original time-zone context.

The model should separate the planned journey, actual observations and external provider data. A changed flight estimate must never silently overwrite the original schedule.

### Core entities

### Journey

One complete door-to-door trip.

`id`, `owner_id`, `title`, `origin`, `destination`, `status`, `current_leg_id`, `tracking_enabled`, `created_at`, `updated_at`, `started_at`, `completed_at`, `schema_version`

### JourneyLeg

One ordered segment of the trip.

`id`, `journey_id`, `sequence`, `mode`, `status`, `origin_place_id`, `destination_place_id`, `scheduled_departure_at`, `scheduled_arrival_at`, `estimated_departure_at`, `estimated_arrival_at`, `actual_departure_at`, `actual_arrival_at`, `provider_id`, `connection_buffer_minutes`

### Place

An airport, station, address or pickup point.

`id`, `name`, `place_type`, `latitude`, `longitude`, `timezone`, `provider_place_id`, `boundary_source`

### TransportDetails

Mode-specific information associated with a leg.

Flight number, airline, airport codes, terminal, gate, PNR reference; train number, stations, coach, seat, platform; or taxi provider, booking reference, pickup and vehicle details when available.

### JourneyEvent

An append-only record of something that happened.

`event_id`, `journey_id`, `leg_id`, `event_type`, `occurred_at`, `recorded_at`, `source`, `payload`, `sequence_number`, `sync_status`

### ProviderSnapshot

A cached snapshot of external travel information.

`provider`, `external_id`, `journey_leg_id`, `fetched_at`, `valid_until`, `provider_updated_at`, `payload_version`, `payload`

Additional entities:

- `JourneyAlert` — notification type, deduplication key, delivery state, creation time and acknowledgement.
- `JourneyTrackingSession` — start/end time, tracking mode, permissions and last observation.
- `JourneySyncCursor` — last acknowledged event sequence and synchronization progress.
- `JourneyConsent` — user-controlled permissions and tracking preferences where consent history is needed.

### Transport and status enums

```
enum class TransportMode {
    FLIGHT,
    TRAIN,
    TAXI,
    BIKE_TAXI,
    METRO,
    BUS,
    WALKING,
    OTHER
}

enum class JourneyStatus {
    DRAFT,
    PLANNED,
    ACTIVE,
    PAUSED,
    COMPLETED,
    CANCELLED
}

enum class LegStatus {
    PLANNED,
    APPROACHING,
    BOARDING,
    IN_TRANSIT,
    ARRIVED,
    DELAYED,
    CANCELLED,
    SKIPPED
}
```

These are illustrative domain types. The final state machine should define which transitions are legal for each transport mode. For example, `BOARDING` is meaningful for flights and trains, but not ordinary walking legs.

### Important schema rules

1. `sequence` must be unique within a journey, with transactional reordering.
2. Planned times and provider estimates are separate fields.
3. Actual arrival is only set when supported by sufficiently reliable evidence.
4. Provider payloads are validated DTOs, not arbitrary data passed directly into the domain.
5. Events have stable IDs and are safe to retry after a lost acknowledgement.
6. Local records must remain usable offline; server synchronization cannot be a prerequisite for editing or viewing a saved trip.
7. Booking references and credentials are sensitive. Encrypt them at rest where appropriate and avoid logging them.
8. Do not store a full GPS trail merely because the trip is active. Record only observations required for the feature, with explicit retention rules.

### Backend persistence

Add migration files in the existing `backend/migrations/versions/` directory. Keep the schema within the existing PostgreSQL/SQLite-compatible conventions wherever practical.

Suggested tables:

- `journeys`
- `journey_legs`
- `journey_events`
- `journey_provider_snapshots`
- `journey_alerts`

Use the existing user, family and device identities rather than inventing parallel account systems. Journey ownership, visibility and family access must be explicitly authorized by the backend. A family relationship must not automatically grant access to every journey or its full location history.

## 4. API design

Keep the existing `/api/v1` prefix and FastAPI service-layer pattern. These are proposed new endpoints, not routes confirmed to exist today.

| Method  | Endpoint                       | Purpose                                |
| ------- | ------------------------------ | -------------------------------------- |
| `POST`  | `/journeys`                    | Create a draft journey                 |
| `GET`   | `/journeys`                    | List authorized journeys               |
| `GET`   | `/journeys/{id}`               | Fetch a journey and ordered legs       |
| `PATCH` | `/journeys/{id}`               | Update editable journey metadata       |
| `POST`  | `/journeys/{id}/legs`          | Add a leg                              |
| `PATCH` | `/journeys/{id}/legs/{leg_id}` | Edit a leg                             |
| `POST`  | `/journeys/{id}/reorder`       | Reorder legs transactionally           |
| `POST`  | `/journeys/{id}/start`         | Start tracking                         |
| `POST`  | `/journeys/{id}/pause`         | Pause tracking                         |
| `POST`  | `/journeys/{id}/complete`      | Complete the journey                   |
| `POST`  | `/journeys/{id}/refresh`       | Refresh supported external travel data |
| `POST`  | `/journeys/{id}/events:batch`  | Idempotent event synchronization       |
| `GET`   | `/journeys/{id}/events`        | Retrieve authorized journey history    |

For compatibility, use the existing API's request and response DTO patterns, strict schema validation and authentication dependencies. Do not make provider credentials or arbitrary URLs configurable through untrusted client input.

### Example: creating a journey

```
{
  "title": "Vellore to Lucknow",
  "origin": {
    "name": "Vellore",
    "place_type": "city"
  },
  "destination": {
    "name": "Home, Lucknow",
    "place_type": "address"
  },
  "legs": [
    {
      "sequence": 0,
      "mode": "TRAIN",
      "origin_name": "Katpadi Junction",
      "destination_name": "KSR Bengaluru",
      "scheduled_departure_at": "2026-11-01T07:45:00+05:30",
      "scheduled_arrival_at": "2026-11-01T11:30:00+05:30",
      "timezone": "Asia/Kolkata"
    }
  ]
}
```

This is an illustrative payload; the dates and times are examples, not a verified timetable. Production requests should use validated place IDs or coordinates where available and define whether the server or client is responsible for resolving names.

### Synchronization contract

Piko's existing durable event queue provides the right foundation.

For each batch:

1. Assign each event a stable UUID and capture its occurrence timestamp.
2. Persist the event locally before attempting transmission.
3. Send events with a batch identifier and stable event IDs.
4. Deduplicate on the server.
5. Acknowledge only after durable acceptance.
6. Retain unacknowledged events and retry with exponential backoff and jitter.
7. Never let an older offline observation overwrite a newer current-state record.

Use explicit conflict rules for user edits. For example, a server-side flight refresh should not overwrite a user's manually corrected destination, and a delayed synchronization of an older leg status should not move a completed journey backwards.

## 5. External API integrations

Build provider interfaces before selecting individual vendors. That allows Piko to use a commercial provider, a self-hosted service, or manual data without changing the journey engine.

Flight provider

Required capabilities: flight-number lookup, scheduled and estimated departure/arrival, status, airports, and terminal/gate information when available.

Refresh before departure, near expected arrival, and on relevant journey transitions. Respect provider quotas and cache responses with freshness timestamps.

Rail provider

Required capabilities: train and station lookup, timetable, running status, estimated arrival and platform information when supported.

For Indian rail, validate licensing, reliability and availability of the selected data source before committing to an integration.

Maps and routing

Calculate route duration and distance between legs, airport/station buffers and estimated connection feasibility. Use geocoding and place boundaries where licensed and available.

Taxi and bike-taxi providers

Support manual entry immediately. Add authorized booking and live vehicle integrations only when the provider permits them. Booking references alone do not grant access to live driver tracking.

### Recommended provider interface

```
interface FlightProvider {
    suspend fun lookupFlight(
        flightNumber: String,
        departureDate: LocalDate
    ): FlightSnapshot
}

interface RailProvider {
    suspend fun getTrainStatus(
        trainNumber: String,
        journeyDate: LocalDate
    ): TrainSnapshot
}

interface RoutingProvider {
    suspend fun estimateRoute(
        origin: Place,
        destination: Place,
        mode: TransportMode
    ): RouteEstimate
}
```

Treat these as design sketches, not compile-ready implementations. Add timeouts, cancellation, typed errors, rate limits and test doubles when implementing them.

Self-hosting requirement: the app must continue to support manual journeys and local tracking if no external API credentials are configured. Store provider secrets on the backend, never in the Android APK. If a deployment owner configures a provider, document the key, terms, quota and data-sharing implications.

## 6. Android permissions and background execution

Piko must request permissions only when the corresponding feature is explained and the user activates it. Journeys should not silently inherit permission to track continuously just because the user previously enabled family location sharing.

### Permission matrix

| Permission / capability       | Purpose                                                    | When to request                                                                   |
| ----------------------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `ACCESS_COARSE_LOCATION`      | Approximate location                                       | When enabling location-based features                                             |
| `ACCESS_FINE_LOCATION`        | More accurate geofencing and arrival detection             | When the user enables precise journey tracking                                    |
| `ACCESS_BACKGROUND_LOCATION`  | Background location beyond foreground-use limits           | Only if the chosen tracking design requires it and the user explicitly enables it |
| `FOREGROUND_SERVICE`          | Foreground tracking service                                | Declare as required for the service                                               |
| `FOREGROUND_SERVICE_LOCATION` | Location foreground service on applicable Android versions | Declare for the location service                                                  |
| `POST_NOTIFICATIONS`          | Journey notifications on Android 13+                       | When enabling journey notifications                                               |
| `INTERNET`                    | Provider access and synchronization                        | Existing app capability                                                           |
| `ACCESS_NETWORK_STATE`        | Detect connectivity changes                                | Existing app capability                                                           |

The repository already declares most of the basic location, network, notification and location foreground-service permissions. Verify the Android SDK targets, service lifecycle and actual permission flows before adding anything.

Additional rules:

- Background location is not automatically necessary for every implementation. Start with a user-started foreground tracking session and geofences; request background permission separately if required by the selected design.
- Android versions and target SDK requirements change. Verify current foreground-service type, background-start and permission rules against the app's configured SDK.
- `WorkManager` is appropriate for deferrable synchronization and refresh tasks, not for guaranteeing exact real-time location sampling.
- A foreground service should have a clear persistent notification, a visible stop/pause control and an appropriate lifecycle.
- Do not rely on hidden services, aggressive wakelocks or continuous GPS to bypass Android's power management.

### How geofence arrival should work

A single GPS reading inside an airport boundary is not enough to confidently announce arrival.

1. Register a geofence for the next relevant station or airport.
2. Receive a geofence transition where supported.
3. Verify the event using available location accuracy, timestamp and current journey context.
4. Apply a dwell or confirmation policy to reduce false arrivals.
5. Persist the event locally.
6. Display the arrival notification once, using a deduplication key.
7. If location permission is missing or stale, show an appropriate uncertainty rather than claiming arrival.

Airport interiors can be difficult for GPS, and station boundaries may overlap. The product should support manual confirmation as a fallback.

## 7. Flight offline mode

This is the most technically distinctive part of Journeys, so it deserves its own design rather than being an ordinary timer in the background.

State 1 — Prepare

When a flight leg becomes active, cache the itinerary, airport information, next leg, time zones and available provider snapshot. Confirm that the local database is ready and show the user what can continue offline.

State 2 — Offline observation

Record permitted local observations with capture timestamps, such as battery level, charging state, connectivity state and location when available and permitted. A target interval of 20 minutes is reasonable for a battery-conscious sampling policy, but Android may defer execution.

State 3 — Durable local queue

Store observations in the existing local event infrastructure, with stable IDs and a bounded retention policy. Avoid frequent GPS acquisition just to satisfy a timer; use cached observations where appropriate and label their age.

State 4 — Reconnect and reconcile

Detect connectivity restoration, upload queued events, refresh flight status and reconcile the locally known state with provider data. A confirmed provider landing event takes precedence over an unverified local inference.

### What the app can and cannot guarantee

- A periodic task is not a precise scheduler. Do not promise a sample exactly every 20 minutes.
- Android can kill the process, defer work or restrict background access. Persist state so the system can recover after a process restart.
- If airplane mode is enabled, network-dependent flight status cannot update. Piko may know that connectivity returned, but that alone does not prove that the aircraft landed.
- If the user force-stops the app, tracking may not resume until the app is launched again.
- Battery readings can be sampled cheaply; continuous location is more expensive. Use different sampling policies for each sensor.
- A flight's actual landing time should come from a trustworthy status source when available. Otherwise show “Possible arrival — awaiting confirmation” rather than a false certainty.

One subtle design choice: don't automatically turn off the device's radios or change system settings. Let the user control airplane mode. Piko should respond to connectivity conditions rather than attempt to control the phone's flight-mode setting.

## 8. Connection-risk engine

The journey engine should reason about the next departure, not just show a list of timestamps.

For each upcoming connection, calculate:

\\[ \text{Available buffer} = \text{Next departure} - \text{Predicted arrival} \\]

\\[ \text{Required buffer} = \text{Transfer time} + \text{Safety margin} \\]

\\[ \text{Slack} = \text{Available buffer} - \text{Required buffer} \\]

The required buffer depends on the connection: a station transfer, airport check-in, security screening and boarding cutoff are not equivalent.

### Illustrative connection assessment

Estimated airport arrival

### 12:35 PM

Boarding cutoff

### 1:30 PM

Remaining buffer

### 55 minutes

Illustrative values only. Piko must obtain the actual flight and transfer details before evaluating a real connection.

The engine should output a confidence level and an explanation:

- Comfortable: sufficient estimated slack.
- Tight: little remaining buffer or uncertain travel time.
- At risk: estimated arrival conflicts with a critical departure cutoff.
- Unknown: stale or insufficient data.

Use conservative defaults and make airport-specific assumptions configurable. Don't automatically rebook tickets or make purchases in the first release. Instead, explain the risk and provide the user with practical options.

## 9. Notification design

Create a centralized notification manager with event-specific templates and deduplication. The journey engine decides what happened; the notification manager decides whether and how to notify.

| Event                          | Example notification                                         |
| ------------------------------ | ------------------------------------------------------------ |
| Station geofence confirmed     | “You've arrived at Katpadi Junction.”                        |
| Train running late             | “Your train is delayed. Checking your Bengaluru connection.” |
| Connection at risk             | “Your airport transfer may be tight. Review your next leg.”  |
| Airport geofence confirmed     | “You've reached Bengaluru Airport.”                          |
| Boarding approaching           | “Your flight's boarding window is approaching.”              |
| Flight status confirms landing | “Your flight has landed in Lucknow.”                         |
| Network restored               | “You're back online. Updating your journey.”                 |
| Home arrival confirmed         | “You've arrived home. Journey complete.”                     |

Use Android notification channels for journey updates and time-sensitive alerts. Provide controls to mute nonessential updates and avoid notifying for every background telemetry event.

A push notification is not a substitute for local scheduling: critical reminders should be scheduled on-device where possible, with server push as a supplementary source.

## 10. Phased implementation roadmap

I would deliver this as seven phases. The estimates below are planning estimates for one developer familiar with the repository, not guaranteed delivery dates.

## 0

Repository audit and contracts

2–3 days

Prerequisite

- Confirm Gradle, Kotlin, SDK and existing test conventions.
- Inspect service lifecycle, SQLite schema, API client and backend migrations.
- Define journey states, provider DTOs, API contracts and privacy boundaries.
- Add a feature entry point consistent with the current Compose UI.

Exit gate: agreed schema, API contract, architecture decision record and test plan.

## 1

Journey Builder MVP

1–2 weeks

Offline-capable

- Create, edit, reorder, save and delete draft journeys.
- Add flight, train, taxi, bike taxi, metro, bus and walking legs.
- Store the journey locally and render an ordered timeline.
- Validate dates, places, time zones and required fields.

Exit gate: a complete manually entered multi-leg trip survives app restarts and works without a network.

## 2

Backend persistence and sync

1–2 weeks

Data integrity

- Add database migrations, API schemas and authorized service methods.
- Implement journey and leg CRUD, reordering and event batches.
- Add idempotent synchronization and conflict handling.
- Add contract tests for user and family authorization.

Exit gate: offline edits synchronize safely without duplicating events or overwriting newer state.

## 3

Journey tracking and notifications

1–2 weeks

Android

- Add tracking start/pause/stop lifecycle.
- Implement geofences and local notifications.
- Integrate battery-aware sampling and connectivity observation.
- Handle missing permissions, stale location and process restarts.

Exit gate: the tracker behaves correctly under permission denial, low battery, connectivity loss and app restarts.

## 4

Flight and rail integrations

1–3 weeks

Provider-dependent

- Implement provider adapters and cache policy.
- Fetch and refresh flight and train details.
- Show provider freshness and data availability.
- Recalculate connection estimates when relevant updates arrive.

Exit gate: provider outages, rate limits and stale responses do not corrupt the itinerary.

## 5

Offline flight mode

1–2 weeks

Advanced

- Cache all required journey data before departure.
- Record permitted telemetry with a battery-conscious policy.
- Recover from process death and reconnect safely.
- Distinguish confirmed landing from inferred arrival.

Exit gate: airplane-mode, process-restart, delayed-work and synchronization tests pass on supported devices.

## 6

Taxi integrations, intelligence and release

2–3 weeks

Hardening

- Add supported taxi tracking integrations.
- Finish connection-risk handling and home-arrival confirmation.
- Run physical-device battery and background execution tests.
- Review security, retention, consent, localization and accessibility.

Exit gate: release criteria pass, integration limits are documented and the Android build is reproducible.

Planning total: approximately 9–17 developer-weeks, with integration availability and background-tracking edge cases being the largest sources of uncertainty. Several tasks can overlap once the API contracts and local data model are stable.

## 11. Task breakdown by repository area

### Android

- Add the `journeys` domain module or package.
- Implement `Journey`, `JourneyLeg`, `Place` and provider snapshot models.
- Extend the local database with transactional journey persistence.
- Build Journey List, Builder, Detail and Active Journey screens.
- Add validation and drag-to-reorder.
- Integrate the tracker with the existing application graph and foreground-service lifecycle.
- Implement geofencing and notification deduplication.
- Implement local-first event queueing and reconnection recovery.
- Add unit, integration and device tests.

### Backend

- Add versioned migrations for journeys, legs, events and snapshots.
- Add strict API DTOs and journey service methods.
- Implement authorization checks for every read and mutation.
- Implement idempotent event-batch ingestion.
- Add provider interfaces, credential configuration and cache expiry.
- Add provider outage, retry and freshness handling.
- Add API, authorization, migration and concurrency tests.

### Web dashboard

The initial implementation can be Android-first, but the existing React dashboard should eventually provide an optional family-facing view of authorized journey milestones.

- Add a Journeys page or section.
- Show the active journey, current leg, last confirmed milestone and freshness.
- Allow family members to view only journeys they are authorized to access.
- Keep full location history separate from simple milestone sharing.
- Reuse the existing dashboard's authentication and layout.

The dashboard is not a blocker for the first Android release. It should not become a second source of truth for journey state.

## 12. Testing and release gates

The feature should have explicit quality gates before it is considered complete.

| Area            | Required scenarios                                                            |
| --------------- | ----------------------------------------------------------------------------- |
| Domain          | Reordering, invalid transitions, missed connections, duplicate events         |
| Persistence     | App killed, reboot, process recreation, interrupted transactions              |
| Synchronization | Duplicate batches, partial acknowledgements, retry/backoff, stale events      |
| Permissions     | Denied, revoked, approximate-only, notifications disabled                     |
| Location        | Poor accuracy, overlapping geofences, false transitions, stale readings       |
| Offline         | Airplane mode, extended outage, queue growth, reconnection                    |
| Provider APIs   | Timeout, malformed response, stale response, rate limit, unavailable data     |
| Privacy         | Unauthorized journey access, credential exposure, retention and deletion      |
| Battery         | Real-device tests with GPS, geofences, foreground service and background work |
| UI              | Accessibility, large text, time zones, long station names, date boundaries    |

For battery performance, establish a baseline before adding Journeys and compare it with the completed feature on representative physical devices. Don't promise a fixed battery percentage until the measurements justify it.

For location and landing detection, record both the event's capture time and the time the system observed or synchronized it. A delayed notification should never be presented as though it occurred in real time.

## 13. Security, privacy and self-hosting requirements

Because Piko is a family-safety product, travel tracking needs stricter controls than an ordinary itinerary app.

- Explicit tracking controls: show when tracking is active and provide pause/stop controls.
- Least privilege: a parent or guardian sees only journeys granted by the product's authorization model.
- Encrypted storage: use the existing device credential vault for secrets; protect sensitive booking references and local records.
- Retention limits: define how long detailed travel observations are retained, independently of the itinerary itself.
- Auditable access: log sensitive server-side access and administrative actions without logging secrets or unnecessary coordinates.
- Self-hosting: external providers must be optional integrations. Document the services, keys and terms required by each deployment.
- No hidden monitoring: avoid silently expanding an existing family-location permission into continuous travel surveillance.
- Honest state: distinguish planned, estimated, detected and provider-confirmed events.

These requirements follow the repository's existing project constitution and should be treated as release blockers, not optional polish.

## 14. Definition of done

Piko Journeys is ready for its first production release only when all of these conditions are satisfied.

## Release checklist

0 of 12

Users can create, edit, reorder and save a multi-leg journey.

Every supported transport type has a useful manual-entry workflow.

The journey works offline and survives process death and app restart.

Tracking permissions and active tracking state are visible and controllable.

Geofence notifications are deduplicated and do not falsely claim arrival.

Flight and train data display freshness and distinguish estimates from confirmed events.

Offline events synchronize idempotently without overwriting newer state.

Connection-risk calculations explain their assumptions and uncertainty.

Flight offline mode recovers from delayed background work and network loss.

Backend authorization, privacy, retention and deletion tests pass.

Android unit tests, backend tests and required physical-device tests pass.

Release documentation explains provider setup, limitations and self-hosted deployment.

## 15. What I recommend doing next

Start with Phase 0, then implement the Journey Builder and local data model together. That establishes the product's shape without making the first milestone dependent on third-party API credentials.

The first pull request should ideally contain:

1. A documented journey domain model and state-transition rules.
2. Local persistence and migration tests.
3. A working Compose-based journey list and multi-leg builder.
4. A manually entered example journey, including train → taxi → flight → taxi.
5. Unit tests proving that reordering, saving, reopening and offline operation work.
6. A short architecture decision record describing how Journeys extends the existing Piko app.

Keep the implementation inside the existing repository and CI pipeline. Do not replace the current tracking service, database or synchronization engine wholesale; extend them where the requirements genuinely overlap.

## Recommended first milestone

Piko Journeys · Phase 0–1

Deliverable: a working Android journey planner that can save a multi-leg itinerary locally, reopen it after an app restart, and display a clear ordered timeline.

No paid API is needed for this milestone. Flight and train details can initially be entered manually, allowing us to validate the UX and data model before adding external dependencies.

Start implementation: Phase 0–1

The long-term goal is for the user to enter a trip once, start tracking, and let Piko coordinate each connection. The right foundation is a reliable, local-first journey engine; flight tracking, smart transfer decisions and taxi integrations can then build on that foundation without compromising Piko's existing safety and privacy guarantees.