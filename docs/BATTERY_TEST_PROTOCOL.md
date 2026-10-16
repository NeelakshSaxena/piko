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
