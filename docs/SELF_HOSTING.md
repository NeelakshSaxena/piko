# Self-hosting Piko

What is verified and what is not is listed in `docs/verification/phase-07-08-report.md`. Commands run from the repository root; PowerShell first, then the Linux/macOS equivalent where it differs.

## 1. What you need
- Python 3.11+, a PostgreSQL database you control (any provider), Node 20+ only if you build the dashboard.
- No SaaS account is required. Push notifications (Firebase, Web Push) are optional and off until configured.
- Everything project-specific stays under the repository (`.venv`, `.data`, `.cache`, `.tmp`). See `docs/LOCAL_ONLY_POLICY.md`.

## 2. First setup (local, loopback only)
```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev,api,test]"      # add ,mcp only if you want the MCP adapter
copy .env.example .env                               # then edit PIKO_DATABASE_URL
cd backend
..\.venv\Scripts\python -m app.cli generate-keys --dir ..\.data\keys   # refuses to overwrite
..\.venv\Scripts\python -m alembic upgrade head
..\.venv\Scripts\python -m app.cli doctor            # must print no [FAIL]
..\.venv\Scripts\python -m app.cli create-family --email you@example.com --family-name "Home"
..\.venv\Scripts\python -m app                       # http://127.0.0.1:8000
```
Linux/macOS: use `.venv/bin/` and forward slashes. The first parent is created only by `create-family` (password typed at a prompt, at least 12 characters); there is no default account and no public signup. Re-running is safe for key generation and backups (both refuse to overwrite) and for migrations (`upgrade head` only moves forward). Do not re-run `create-family` for an account that already exists.

`doctor` is read-only. It checks binding, the public URL, key files (presence, length, POSIX permissions), that the JWT key loads, database reachability, that migrations are at head, and whether MCP and push are on. It prints setting names, never values.

## 3. Unsafe defaults are refused
- The server will not bind a non-loopback address unless `PIKO_ALLOW_PUBLIC_BIND=true`, and then `PIKO_PUBLIC_BASE_URL` must be `https://`.
- `PIKO_ENV=production` requires https, bcrypt rounds ≥ 12 and no wildcard hosts/origins.
- MCP is off unless `PIKO_MCP_ENABLED=true`, and is local stdio only (`docs/MCP.md`).

## 4. Making it reachable (you are responsible for all of this)
Put a TLS-terminating reverse proxy (Caddy, nginx, Traefik) in front, keep Piko bound to loopback or a private interface, open only 443 in the firewall, set `PIKO_PUBLIC_BASE_URL`, `PIKO_ALLOWED_ORIGINS` and `PIKO_ALLOWED_HOSTS` to your real names, and keep `.data/keys` readable only by the service account. Serve the dashboard (`web/dist`) from the same proxy or a static host. Hosted-on-Vercel details: `docs/DEPLOYMENT.md`.

You also own: DNS, certificate renewal, OS and dependency updates, monitoring, secret storage and rotation, retention (section 7), and access to servers and backups.

## 5. Health checks
`GET /api/v1/health/live` (process is up) and `GET /api/v1/health/ready` (database reachable; 503 when not). Neither returns secrets.

## 6. Backup and restore
```powershell
python -m app.cli backup --out .data\backups\piko-2026-10-27.gz     # also writes .gz.sha256
python -m app.cli restore --file .data\backups\piko-2026-10-27.gz   # into an EMPTY schema at the SAME revision
```
- Backs up the configured schema in one consistent snapshot. Never overwrites an existing file.
- **Restore never deletes or replaces data.** It refuses a schema that has any rows, a different migration revision, a damaged/incomplete file, or a checksum mismatch, and it is all-or-nothing.
- To restore: point `PIKO_DB_SCHEMA` at a new or emptied schema, run `alembic upgrade <revision printed by the backup>`, then `restore`, then `doctor`, then log in.
- The file contains password and credential hashes and sealed push data: store it encrypted (for example with `age` or your backup tool) and off the same disk. **The JWT/HMAC key files are not in the backup**; back them up separately, or sessions, pairing codes and sealed push data from the old install cannot be used.
- A backup is valid only after a restore test. The test suite restores a populated schema and logs in to the copy; do your own drill after each change of host.
- Deleted-data note: a backup keeps what existed when it was taken; deleting a family or letting retention run does not remove it from older backups.
- `pg_dump`/`pg_restore` also work if you have them; this tool exists because many hosts do not.

## 7. Retention
`python -m app.cli retention` is a dry run; `--apply` deletes messages older than 90 days, audit older than 365 days and delivered outbox rows older than 30 days (defaults in `.env.example`). SOS incidents are never auto-deleted. Run it on a schedule you choose.

## 8. Upgrade and rollback
1. `python -m app.cli backup --out ...` and confirm it printed a checksum.
2. Stop the server; pull the new code; reinstall dependencies; `alembic upgrade head`; `doctor`; start.
3. Rollback: stop; `alembic downgrade <previous revision>` (0006 and 0005 downgrades remove only their own additions; 0005 drops push registrations and queued notifications) or restore the pre-upgrade backup into a fresh schema at that revision and point `PIKO_DB_SCHEMA` at it. Test the path on a copy first.

## 9. Uninstall and your data
Stop the service, then drop the Piko schema (`DROP SCHEMA piko CASCADE` — irreversible; do it yourself, deliberately) and delete `.data/`, `.venv/`, and your backups. Nothing is sent to the Piko maintainers; there is no phone-home.

## 10. Docker
Optional and not provided. If you containerise it, the Docker engine stores images and caches under its own data root, which may not be on the drive you intended; configure it explicitly before claiming the install is project-local.
