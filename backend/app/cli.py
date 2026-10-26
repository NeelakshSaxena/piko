"""Operator commands: `python -m app.cli generate-keys | create-family | generate-push-secrets | retention | outbox
| mcp-token | mcp-revoke | mcp`.

There is no public signup endpoint (docs/API_CONTRACTS.md defines none), so the first parent and
family are created here. Passwords are read from a prompt, never from argv or the environment.
"""

import argparse
import getpass
import os
import sys
from collections.abc import Callable
from pathlib import Path

from app.core.config import get_settings
from app.core.security import generate_rsa_private_pem, password_is_acceptable_length
from app.db.session import make_engine, make_session_factory
from app.services.bootstrap import create_family_with_parent

MIN_PASSWORD_LENGTH = 12


def generate_keys(directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    targets: dict[str, Callable[[], bytes]] = {
        "jwt_private.pem": generate_rsa_private_pem,
        "hmac.key": lambda: os.urandom(32),
    }
    for name in targets:
        if (directory / name).exists():
            print(f"refusing to overwrite existing {directory / name}", file=sys.stderr)
            return 1
    for name, make in targets.items():
        # O_EXCL: never replace an existing key; mode 0600 from creation (no chmod race).
        fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(make())
    print(f"wrote key files to {directory}")
    print(f"set PIKO_JWT_PRIVATE_KEY_FILE={directory / 'jwt_private.pem'}")
    print(f"set PIKO_HMAC_KEY_FILE={directory / 'hmac.key'}")
    return 0


def create_family(email: str, family_name: str) -> int:
    password = getpass.getpass("Password (min 12 chars): ")
    if len(password) < MIN_PASSWORD_LENGTH or not password_is_acceptable_length(password):
        print("password must be 12 characters and at most 72 bytes", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat password: ") != password:
        print("passwords differ", file=sys.stderr)
        return 1
    settings = get_settings()
    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        user_id, family_id = create_family_with_parent(
            db, settings, email=email, password=password, family_name=family_name
        )
    print(f"created user {user_id} and family {family_id}")
    return 0


def generate_push_secrets(directory: Path) -> int:
    """Creates the Web Push (VAPID) key pair and the outbox scheduler token. The private key and the token
    stay in files (mode 0600) that are never committed; only the public key is printed for the config."""
    import base64
    import secrets

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    directory.mkdir(parents=True, exist_ok=True)
    private_path, token_path = directory / "vapid_private.pem", directory / "outbox_run_token"
    for path in (private_path, token_path):
        if path.exists():
            print(f"refusing to overwrite existing {path}", file=sys.stderr)
            return 1
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    for path, data in ((private_path, pem), (token_path, secrets.token_urlsafe(32).encode())):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    print(f"wrote {private_path} and {token_path}")
    print(f"set PIKO_VAPID_PRIVATE_KEY_FILE={private_path}")
    print(f"set PIKO_VAPID_PUBLIC_KEY={base64.urlsafe_b64encode(public).decode().rstrip('=')}")
    print(f"set PIKO_OUTBOX_RUN_TOKEN_FILE={token_path}")
    return 0


def run_retention(apply: bool) -> int:
    from app.services.retention import RetentionService

    settings = get_settings()
    factory = make_session_factory(make_engine(settings))
    report = RetentionService(settings).run(factory, apply=apply)
    mode = "deleted" if apply else "would delete (dry run; pass --apply to delete)"
    for name, count in report.counts.items():
        print(f"{name}: {mode} {count}")
    if report.more_remaining:
        print("more remain: run again")
    return 0


def run_outbox(loop: bool, interval: int) -> int:
    import time

    from app.main import build_transports
    from app.services.notifications import NotificationService
    from app.services.push import PushRegistry

    settings = get_settings()
    hmac_key = settings.hmac_key_file.read_bytes()
    factory = make_session_factory(make_engine(settings))
    worker = NotificationService(
        settings, PushRegistry(settings, hmac_key), build_transports(settings)
    )
    while True:
        result = worker.drain(factory)
        print(
            f"accepted={result.accepted} retried={result.retried} dead={result.dead} "
            f"skipped={result.skipped} expired={result.expired} waiting={result.waiting_for_transport}",
            flush=True,
        )
        if not loop:
            return 0
        time.sleep(interval)


def run_doctor() -> int:
    from app.services.doctor import exit_code, run_checks

    checks = run_checks(get_settings())
    for c in checks:
        print(f"[{c.status.upper():4}] {c.name}: {c.detail}")
    return exit_code(checks)


def run_backup(out: Path) -> int:
    from app.services.backup import BackupError, backup

    try:
        report = backup(make_engine(get_settings()), out)
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"backup written: {report.path}  (revision {report.revision})")
    print(f"sha256: {report.sha256}")
    for name, n in report.counts.items():
        print(f"  {name}: {n}")
    print("This file holds password and credential hashes: store it as carefully as the database.")
    return 0


def run_restore(source: Path) -> int:
    from app.services.backup import BackupError, restore

    settings = get_settings()
    try:
        report = restore(make_engine(settings), source)
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"restored {sum(report.counts.values())} rows into schema {settings.db_schema}")
    return 0


def issue_mcp_token(email: str, ttl_hours: int) -> int:
    from sqlalchemy import select

    from app.core.security import TokenService
    from app.db.models import User
    from app.mcp_server.auth import issue_token

    settings = get_settings()
    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        user_id = db.scalar(select(User.id).where(User.email == email.strip().lower()))
        if user_id is None:
            print("no such user", file=sys.stderr)
            return 1
        try:
            issued = issue_token(
                db, TokenService(settings), settings, user_id=user_id, ttl_hours=ttl_hours
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"session id: {issued.session_id}  (use it to revoke)")
    print(f"expires:    {issued.expires_at.isoformat()}")
    print("token (shown once; give it to the MCP client's launcher as PIKO_MCP_TOKEN):")
    print(issued.token)
    return 0


def revoke_mcp_token(session_id: str) -> int:
    import uuid

    from app.mcp_server.auth import revoke_token

    try:
        parsed = uuid.UUID(session_id)
    except ValueError:
        print("session id must be a UUID", file=sys.stderr)
        return 1
    settings = get_settings()
    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        found = revoke_token(db, parsed)
    print("revoked" if found else "no MCP credential with that session id")
    return 0 if found else 1


def run_mcp() -> int:
    from app.mcp_server.server import run_stdio

    return run_stdio(get_settings())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    keys = sub.add_parser("generate-keys", help="create JWT signing key and HMAC key files")
    keys.add_argument("--dir", type=Path, default=Path(".data/keys"))
    fam = sub.add_parser("create-family", help="create the first parent account and family")
    fam.add_argument("--email", required=True)
    fam.add_argument("--family-name", required=True)
    push = sub.add_parser(
        "generate-push-secrets", help="create the VAPID key pair and scheduler token"
    )
    push.add_argument("--dir", type=Path, default=Path(".data/keys"))
    ret = sub.add_parser(
        "retention", help="delete data past its retention period (dry run by default)"
    )
    ret.add_argument("--apply", action="store_true", help="actually delete")
    box = sub.add_parser("outbox", help="deliver queued push notifications")
    box.add_argument("--loop", action="store_true", help="keep running instead of one pass")
    box.add_argument("--interval", type=int, default=10, help="seconds between passes with --loop")
    sub.add_parser("doctor", help="check this install's configuration (read-only)")
    bak = sub.add_parser("backup", help="write a logical backup of the configured schema")
    bak.add_argument("--out", type=Path, required=True)
    res = sub.add_parser("restore", help="restore a backup into an empty, migrated schema")
    res.add_argument("--file", type=Path, required=True)
    mtok = sub.add_parser(
        "mcp-token", help="issue a read-only MCP credential for one adult account"
    )
    mtok.add_argument("--email", required=True)
    mtok.add_argument("--ttl-hours", type=int, default=24 * 7)
    mrev = sub.add_parser("mcp-revoke", help="revoke an MCP credential by its session id")
    mrev.add_argument("--session-id", required=True)
    sub.add_parser(
        "mcp", help="run the read-only MCP adapter on stdio (needs PIKO_MCP_ENABLED=true)"
    )
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return run_doctor()
    if args.command == "backup":
        return run_backup(args.out)
    if args.command == "restore":
        return run_restore(args.file)
    if args.command == "mcp-token":
        return issue_mcp_token(args.email, args.ttl_hours)
    if args.command == "mcp-revoke":
        return revoke_mcp_token(args.session_id)
    if args.command == "mcp":
        return run_mcp()
    if args.command == "generate-keys":
        return generate_keys(args.dir)
    if args.command == "generate-push-secrets":
        return generate_push_secrets(args.dir)
    if args.command == "retention":
        return run_retention(args.apply)
    if args.command == "outbox":
        return run_outbox(args.loop, args.interval)
    return create_family(args.email, args.family_name)


if __name__ == "__main__":
    raise SystemExit(main())
