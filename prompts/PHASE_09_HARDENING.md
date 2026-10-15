# Phase 9 — Hardening

## Goal
Run the full threat-model-driven test plan and close defects before release.

## Required work
- Dependency vulnerability audit and lockfile review.
- Secret scanning.
- Cross-family authorization matrix.
- API and MCP boundary tests.
- Rate/size/time limits.
- Data retention/deletion tests.
- Backup restore drill.
- Network-loss and offline-recovery tests.
- Android permission/background/battery tests on physical devices.
- UI accessibility and stale-data correctness review.
- Logs review for secret/location/message leakage.
- Local-path verification.

## Rules
Do not fix failures by weakening controls or removing tests. Record each finding, severity, reproduction, fix, and regression test. Critical/high findings block release unless a human explicitly risk-accepts them in writing.

## Battery evidence
Record device, Android version, mode, duration, screen state, location settings, network conditions, battery start/end, baseline, repeat count, and result spread. Do not generalize one device result to all devices.

## Exit gate
All required tests pass; no unaccepted critical/high issue; verification report is reproducible.
