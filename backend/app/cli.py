"""Operator commands: `python -m app.cli generate-keys | create-family | generate-push-secrets | retention | outbox`.

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
    args = parser.parse_args(argv)
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
