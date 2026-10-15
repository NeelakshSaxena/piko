# Local-Only Development Policy

## Goal

Project-specific files, dependencies, caches, toolchains, virtual environments, build output, test data, and local services must stay beneath the Piko repository root. The user requires that nothing for this project be installed on another drive.

This policy applies to scripts and coding agents. Never assume a default cache path is acceptable.

## Required layout

- Python: `.venv/`
- pip cache: `.cache/pip/`
- npm cache: `.cache/npm/`
- Node runtime if locally downloaded: `.tools/node/`
- Android SDK if locally installed: `.tools/android-sdk/`
- Gradle user home: `.gradle-home/`
- temporary data: `.tmp/`
- application/test data: `.data/`
- generated reports: `artifacts/`

The repository itself should be located on the user's chosen project drive. Do not choose a drive or move existing files without asking.

## Python

Before creating the environment, confirm the root and free space. Use the project interpreter and `.venv`. Set `PIP_CACHE_DIR` to `.cache/pip` for commands. Do not use `pip install --user`, global pip, or system Python package installation. Pin dependencies with a lock mechanism before release.

Suggested PowerShell environment for the current terminal:
```powershell
$env:PIP_CACHE_DIR = "$PWD\.cache\pip"
$env:TEMP = "$PWD\.tmp"
$env:TMP = "$PWD\.tmp"
```

Suggested shell environment:
```bash
export PIP_CACHE_DIR="$PWD/.cache/pip"
export TMPDIR="$PWD/.tmp"
```

## Node/web

Use a project-local Node runtime if Node must be downloaded. Set npm cache to `.cache/npm`; ensure package installation creates `web/node_modules` inside the repository. Do not use global package managers to install project packages.

## Android/Gradle

Set `GRADLE_USER_HOME` to `.gradle-home`. If Android SDK is needed, use `.tools/android-sdk` and configure `ANDROID_HOME`/`ANDROID_SDK_ROOT` for the current process only. Do not change global environment variables or machine-wide settings without explicit approval. Android Studio itself may be installed outside the repository by the user; do not install it or change its location automatically.

## Docker caveat

Docker's images, layers, and build cache normally live in the Docker engine's configured data root, which may be outside the project directory. Project bind mounts and volumes alone do not make all Docker data project-local. Therefore:
- Docker is not the default local workflow under the strict rule.
- Do not run `docker pull`, `docker build`, or `docker compose up` until the operator confirms the Docker data root is on the approved drive.
- The self-hosting guide must explain this before offering Docker as an option.

## Database

Local database files and test fixtures live in `.data`. Never copy real location data into fixtures. PostgreSQL data directories for local self-hosting must be under `.data` if PostgreSQL is installed/runnable project-locally. Do not silently use a remote database.

## Guard script requirements

`scripts/verify_local_paths.py` should inspect configured paths and fail if any project-controlled path resolves outside the root. It must not scan or print unrelated user files. It should be run before dependency installation and before phase completion.

## Setup safety

Setup scripts must:
1. print the resolved project root;
2. print all intended install/cache/data destinations;
3. check whether the target already exists;
4. avoid destructive overwrite;
5. stop if any path is outside the project root;
6. require explicit approval before downloads or installation;
7. record tool versions and results;
8. never auto-elevate privileges.

## Limits

Operating-system components, GPU drivers, and an IDE the user has already installed are not project dependencies and must not be altered. If a required system service cannot meet the project-local rule, stop and explain the blocker rather than silently installing it elsewhere.
