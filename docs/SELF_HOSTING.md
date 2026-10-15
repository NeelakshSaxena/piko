# Self-Hosting Guide — Design Requirements

This is a specification; final commands must be verified against the actual implementation before publication.

## Goals

A technically capable user should be able to:
1. clone or download Piko;
2. run a preflight/doctor check;
3. configure a local environment file;
4. initialize the database and migrations;
5. start backend and web UI;
6. create the first admin/parent account securely;
7. pair an Android device;
8. configure backups and updates.

## Local-only development

- Default bind address is `127.0.0.1`.
- Use `.venv`, `.cache`, `.tools`, `.data`, `.tmp`, and `.gradle-home` under the project root.
- Use synthetic test data.
- No cloud account is mandatory.
- No telemetry is sent to the Piko project maintainers.
- No default password or committed secret.
- Setup is repeatable and does not destroy existing data.

## Production self-hosting

The operator is responsible for:
- a supported OS and hardware;
- domain and TLS certificate for remote access;
- secure reverse proxy and firewall;
- unique secret generation and safe secret storage;
- database migrations and verified backups;
- restore drills;
- security updates;
- monitoring and incident response;
- data retention and deletion;
- access to the server and backups.

Remote MCP must not be enabled until authentication, OAuth/resource validation, TLS, rate limits, and authorization tests pass.

## Deployment modes

1. Local developer mode: loopback only, local data.
2. Private LAN mode: explicit opt-in, firewall guidance, authentication required.
3. Internet-facing mode: only after production hardening and TLS/reverse-proxy configuration.

Docker is optional and must be accompanied by a warning that the Docker engine may store images/cache outside the project root. It is not compliant with the strict local-only rule unless the operator confirms the engine data root is on the approved drive.

## Backup and restore

Document:
- what is included;
- encryption expectations;
- key management;
- restore command;
- compatibility across versions;
- verification that restore works;
- how deletion/retention affects backups.

Never claim a backup is valid until a restore test succeeds.
