# Skill: Android Battery and Offline Reliability

Use for Android collectors, services, networking, scheduling, or location changes.
- Avoid one-minute GPS activation as a default polling implementation.
- Respect OS permissions, background limits, and foreground-service rules.
- Persist events before sending.
- Test process death, network loss, duplicate batches, partial acknowledgements, reboot if supported, and low storage.
- Use bounded retries with jitter.
- Measure payload size and physical-device battery use with a written protocol.
- Do not claim the 1–2%/7–8 hour target without repeatable evidence.
