# Skill: Self-Hosting and Local Paths

Use for bootstrap, deployment, database, Docker, or tooling changes.
- Resolve all paths and prove they remain under repository root.
- Print intended destinations before install/download/write operations.
- Never install globally or change machine-wide settings.
- Warn that Docker images/cache live in the engine data root, not necessarily the repo.
- Bind to localhost by default.
- Require secure secrets, TLS for remote access, backup/restore, migrations, health checks, and safe upgrades.
- Never overwrite existing user data.
