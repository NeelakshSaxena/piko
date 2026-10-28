# Android battery measurement protocol

**Status: protocol only. No battery result exists.** The product target of 1-2% battery use over
7-8 hours is a target to measure (AGENTS.md section 4), not a claim. Nothing in this repository may
state that the target is met until a physical-device run recorded under `docs/verification/` shows
it. An emulator cannot measure battery drain and must not be used for this.

## What is measured
Battery used by Piko attributable to location sharing over a fixed window, for each mode
(POLLING and REALTIME) separately, with the phone otherwise idle.

## Equipment and conditions
- One physical phone per run (record make, model, Android version, battery health if known).
- Screen off during the window except where a step says otherwise; no other apps in use; same
  location (record "stationary indoors" or "walking route" for the run); Wi-Fi or mobile data
  (record which, and signal quality); battery saver off unless that is the case under test.
- Start between 90% and 100% charge, unplugged, `adb` over a network or a USB cable removed
  during the window (USB charging corrupts the result). Developer options may stay on.
- Run length 8 hours, repeated 3 times per mode and condition. Report all runs, not the best.
- Sharing is started from the open app, as the product requires. The only family data used is a
  synthetic test family on a local or test server; never real family locations.

## Procedure (per run)
1. Charge to 100%, unplug, reboot, wait 10 minutes.
2. `adb shell dumpsys batterystats --reset` (project adb: `.tools\android\platform-tools\adb.exe`).
3. Note the start time, battery %, charge counter (`adb shell dumpsys battery`).
4. Open Piko, choose the mode, start sharing, lock the screen, disconnect USB.
5. After 8 hours reconnect and immediately run:
   - `adb shell dumpsys batterystats --charged app.piko.android > artifacts/android/battery/<run>-batterystats.txt`
   - `adb shell dumpsys battery` and note the end %.
   - `adb bugreport artifacts/android/battery/<run>-bugreport.zip` (contains location data of the
     test phone only; keep it in `artifacts/`, which is not committed).
6. From the output record: Piko's estimated mAh and percent, wakelock time, foreground-service
   time, network bytes sent/received, number of GPS/fused location requests, and total battery
   drop. Compute the percentage attributable to Piko and the percentage of the whole drop.
7. In the app (Offline Shield card) record events acknowledged and the last upload size so cost per
   delivered event can be reported.

## Required scenarios
| Scenario | Why |
|---|---|
| POLLING, stationary, good network | the expected common case |
| POLLING, walking (movement-gated updates) | cost when updates really flow |
| REALTIME, stationary and walking | cost of high accuracy and prompt uploads |
| POLLING, no network for 2 h then restored | offline queue plus backlog upload cost |
| Battery saver on, Doze forced (`adb shell dumpsys deviceidle force-idle`) | OS restrictions; record what stops and what the UI shows |
| Location permission revoked mid-run (`adb shell pm revoke`) | must stop truthfully, not drain |

## Reporting
Per run: device, conditions, mode, start/end battery, Piko mAh/percent, counters above, anomalies.
State the spread across the three repeats. Report failures to meet 1-2% as plainly as passes. Any
OS behaviour that kills or throttles the service (OEM battery managers, Doze) is documented as a
limitation with the documented fallback; platform restrictions are never evaded.

## Not claimed
Battery use on any device, in any mode, until runs exist. No emulator figure is acceptable.


## Journeys additions (not yet run on any device)

Run the baseline first (app installed, sharing as in the main protocol), then repeat with each of these for the same
duration on the same physical phone, charge level and network, and record the difference. No figure is claimed until
runs exist.

1. A followed journey, location detection **off**: alarms and the 20-minute job only (flight leg current, backup on).
2. A followed journey with location detection **on**, phone stationary, then phone moving.
3. Doze: leave the phone idle and unplugged for 2 hours with a flight leg current; count readings actually taken
   against the ~6 requested, and note how late the reminder alarms were.
4. OEM battery manager on (the vendor's default saver): does the foreground service survive 30 minutes with the screen off?
5. Airplane mode for 1 hour while following: readings accumulate locally, are delivered after reconnecting, and no
   "landed" statement appears.
6. Force-stop, then open the app: the screen must say location detection is not running; alarms must be rebuilt after
   a reboot.
7. Arrival detection while moving into and past the chosen place (a bus or a walk): record whether it fires once, late,
   early, or not at all; false arrivals while passing the area count as failures.
